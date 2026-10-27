"""Adaptadores PostgreSQL de Clientes; una conexión y una transacción por comando."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from app.modules.clientes.application.ports import ClientRow, DuplicateName

SELECT_FIELDS = "id,nombre,rfc,sector,contacto,estado_id,creado_en,creado_por,actualizado_en,actualizado_por"
SECTOR_TRIM = " \t\n\r\f\v"


class PostgresClientRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list(self, query: str, state: str, sector: str, after_id: int | None, limit: int) -> tuple[int, list[ClientRow]]:
        clauses = [{"vigentes": "estado_id <> -1", "activos": "estado_id = 1", "inactivos": "estado_id = 0", "eliminados": "estado_id = -1"}[state]]
        args: list[object] = []
        if query:
            clauses.append("(nombre ILIKE %s OR rfc ILIKE %s OR sector ILIKE %s)")
            term = f"%{query}%"
            args.extend((term, term, term))
        if sector:
            clauses.append("upper(btrim(sector,%s)) = %s")
            args.extend((SECTOR_TRIM, sector.upper()))
        where = " AND ".join(clauses)
        total = self.conn.execute(f"SELECT count(*) AS n FROM cfg.cliente WHERE {where}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("id > %s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {SELECT_FIELDS} FROM cfg.cliente WHERE {' AND '.join(clauses)} ORDER BY id LIMIT %s",
            (*args, limit),
        ).fetchall()
        return total, rows

    def sectors(self) -> list[str]:
        rows = self.conn.execute(
            """SELECT DISTINCT upper(btrim(sector,%s)) AS sector
                 FROM cfg.cliente
                WHERE sector IS NOT NULL AND btrim(sector,%s) <> ''
                ORDER BY sector""",
            (SECTOR_TRIM, SECTOR_TRIM),
        ).fetchall()
        return [row["sector"] for row in rows]

    def get(self, client_id: int) -> ClientRow | None:
        return self.conn.execute(
            f"""SELECT {', '.join('c.' + field for field in SELECT_FIELDS.split(','))},
                        creador.nombre AS creado_por_nombre, editor.nombre AS actualizado_por_nombre
                   FROM cfg.cliente c
                   LEFT JOIN seg.usuario creador ON creador.id=c.creado_por
                   LEFT JOIN seg.usuario editor ON editor.id=c.actualizado_por
                  WHERE c.id=%s""",
            (client_id,),
        ).fetchone()

    def get_for_update(self, client_id: int, *, include_deleted: bool = False) -> ClientRow | None:
        state_clause = "" if include_deleted else " AND estado_id<>-1"
        return self.conn.execute(
            f"SELECT {SELECT_FIELDS} FROM cfg.cliente WHERE id=%s{state_clause} FOR UPDATE", (client_id,),
        ).fetchone()

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        return self.conn.execute(
            "SELECT EXISTS (SELECT 1 FROM cfg.cliente WHERE estado_id<>-1 AND lower(regexp_replace(btrim(nombre,%s), '[[:space:]]+', ' ', 'g'))=lower(%s) AND (%s::int IS NULL OR id<>%s::int)) AS existe",
            (SECTOR_TRIM, name, exclude_id, exclude_id),
        ).fetchone()["existe"]

    def create(self, values: ClientRow, actor_id: int) -> ClientRow:
        try:
            return self.conn.execute(
                f"""INSERT INTO cfg.cliente(nombre,rfc,sector,contacto,estado_id,creado_por,actualizado_por)
                     VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING {SELECT_FIELDS}""",
                (values["nombre"], values.get("rfc"), values.get("sector"), values.get("contacto"), values["estado_id"], actor_id, actor_id),
            ).fetchone()
        except UniqueViolation:
            raise DuplicateName from None

    def update(self, client_id: int, changes: ClientRow, actor_id: int) -> ClientRow:
        assignments = [sql.SQL("{} = %s").format(sql.Identifier(key)) for key in changes]
        assignments.extend((sql.SQL("actualizado_en = GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"), sql.SQL("actualizado_por = %s")))
        statement = sql.SQL("UPDATE cfg.cliente SET {} WHERE id=%s RETURNING " + SELECT_FIELDS).format(sql.SQL(", ").join(assignments))
        try:
            return self.conn.execute(statement, (*changes.values(), actor_id, client_id)).fetchone()
        except UniqueViolation:
            raise DuplicateName from None

    def soft_delete(self, client_id: int, actor_id: int) -> ClientRow:
        return self.conn.execute(
            f"""UPDATE cfg.cliente
                SET estado_id=-1,
                    actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond'),
                    actualizado_por=%s
                WHERE id=%s RETURNING {SELECT_FIELDS}""",
            (actor_id, client_id),
        ).fetchone()

    def restore(self, client_id: int, actor_id: int) -> ClientRow:
        try:
            return self.conn.execute(
                f"""UPDATE cfg.cliente
                    SET estado_id=0,
                        actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond'),
                        actualizado_por=%s
                    WHERE id=%s RETURNING {SELECT_FIELDS}""",
                (actor_id, client_id),
            ).fetchone()
        except UniqueViolation:
            raise DuplicateName from None

    def change_state(self, client_id: int, state: int, actor_id: int) -> ClientRow:
        return self.conn.execute(
            f"""UPDATE cfg.cliente
                SET estado_id=%s,
                    actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond'),
                    actualizado_por=%s
                WHERE id=%s RETURNING {SELECT_FIELDS}""",
            (state, actor_id, client_id),
        ).fetchone()


class PostgresAccountStateReader:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def locked_states_for_client(self, client_id: int) -> list[int]:
        # FOR SHARE conserva el bloqueo frente a una activación concurrente.
        rows = self.conn.execute("SELECT estado_id FROM cfg.cuenta WHERE cliente_id=%s FOR SHARE", (client_id,)).fetchall()
        return [row["estado_id"] for row in rows]


def _json_ready(row: ClientRow | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: value.isoformat() if isinstance(value, (date, datetime)) else value for key, value in row.items()}


class PostgresClientAuditWriter:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def record(self, actor_id: int, action: str, entity: ClientRow, before: ClientRow | None = None) -> None:
        self.conn.execute(
            """INSERT INTO aud.auditoria(usuario_id,modulo,accion,entidad_tipo,entidad_id,entidad_nombre,antes,despues)
               VALUES (%s,'clientes',%s,'Cliente',%s,%s,%s,%s)""",
            (actor_id, action, str(entity["id"]), entity["nombre"], Jsonb(_json_ready(before)) if before else None, Jsonb(_json_ready(entity))),
        )


class PostgresClientUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.clients = PostgresClientRepository(conn)
        self.accounts = PostgresAccountStateReader(conn)
        self.audit = PostgresClientAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresClientUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
