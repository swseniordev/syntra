"""Persistencia de grupos y sus relaciones dentro de una transacción."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter

FIELDS = "id,nombre,descripcion,estado_id,creado_en,creado_por,actualizado_en,actualizado_por"
EDITABLE = frozenset({"nombre", "descripcion", "estado_id"})


class PostgresGroupRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def lock_names(self) -> None:
        # El modelo oficial no tiene índice único para nombre de grupo. Serializa
        # altas, renombres y restauraciones realizadas por esta API.
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('syntra_grupo_nombre'))")

    def _members(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return rows
        ids = [row["id"] for row in rows]
        users = {group_id: [] for group_id in ids}
        accounts = {group_id: [] for group_id in ids}
        for link in self.conn.execute(
            "SELECT grupo_id,usuario_id FROM seg.grupo_usuario WHERE grupo_id=ANY(%s) ORDER BY usuario_id", (ids,),
        ):
            users[link["grupo_id"]].append(link["usuario_id"])
        for link in self.conn.execute(
            "SELECT grupo_id,cuenta_id FROM seg.grupo_cuenta WHERE grupo_id=ANY(%s) ORDER BY cuenta_id", (ids,),
        ):
            accounts[link["grupo_id"]].append(link["cuenta_id"])
        for row in rows:
            row["usuario_ids"] = users[row["id"]]
            row["cuenta_ids"] = accounts[row["id"]]
        return rows

    def list(self, query: str, state: str, after_id: int | None, limit: int) -> tuple[int, list[dict[str, Any]]]:
        clauses = [{"vigentes": "estado_id<>-1", "activos": "estado_id=1",
                    "inactivos": "estado_id=0", "eliminados": "estado_id=-1"}[state]]
        args: list[object] = []
        if query:
            clauses.append("(nombre ILIKE %s OR descripcion ILIKE %s)")
            args.extend((f"%{query}%", f"%{query}%"))
        total = self.conn.execute(f"SELECT count(*) AS n FROM seg.grupo WHERE {' AND '.join(clauses)}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("id>%s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM seg.grupo WHERE {' AND '.join(clauses)} ORDER BY id LIMIT %s", (*args, limit),
        ).fetchall()
        return total, self._members(rows)

    def get(self, group_id: int, *, for_update: bool = False) -> dict[str, Any] | None:
        row = self.conn.execute(
            f"SELECT {FIELDS} FROM seg.grupo WHERE id=%s" + (" FOR UPDATE" if for_update else ""), (group_id,),
        ).fetchone()
        return self._members([row])[0] if row else None

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM seg.grupo WHERE lower(nombre)=lower(%s) AND estado_id<>-1 "
            "AND (%s::int IS NULL OR id<>%s::int)) AS existe", (name, exclude_id, exclude_id),
        ).fetchone()["existe"]

    def references_exist(self, user_ids: list[int], account_ids: list[int]) -> bool:
        # FOR SHARE impide la eliminación lógica concurrente entre validación e inserción.
        if user_ids:
            rows = self.conn.execute(
                "SELECT id FROM seg.usuario WHERE id=ANY(%s) AND estado_id<>-1 FOR SHARE", (user_ids,),
            ).fetchall()
            if len(rows) != len(user_ids):
                return False
        if account_ids:
            rows = self.conn.execute(
                "SELECT id FROM cfg.cuenta WHERE id=ANY(%s) AND estado_id<>-1 FOR SHARE", (account_ids,),
            ).fetchall()
            if len(rows) != len(account_ids):
                return False
        return True

    def _replace_links(self, group_id: int, values: dict[str, Any]) -> None:
        for key, table, column in (("usuario_ids", "seg.grupo_usuario", "usuario_id"),
                                    ("cuenta_ids", "seg.grupo_cuenta", "cuenta_id")):
            if key not in values:
                continue
            ids = values[key]
            self.conn.execute(f"DELETE FROM {table} WHERE grupo_id=%s AND NOT ({column}=ANY(%s))", (group_id, ids))
            for identifier in ids:
                self.conn.execute(
                    f"INSERT INTO {table}(grupo_id,{column}) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (group_id, identifier),
                )

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        row = self.conn.execute(
            "INSERT INTO seg.grupo(nombre,descripcion,estado_id,creado_por,actualizado_por) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (values["nombre"], values.get("descripcion"), values.get("estado_id", 1), actor_id, actor_id),
        ).fetchone()
        self._replace_links(row["id"], values)
        return self.get(row["id"])

    def update(self, group_id: int, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        fields = {key: value for key, value in values.items() if key in EDITABLE}
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields]
        assignments.extend((sql.SQL("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"),
                            sql.SQL("actualizado_por=%s")))
        statement = sql.SQL("UPDATE seg.grupo SET {} WHERE id=%s").format(sql.SQL(",").join(assignments))
        self.conn.execute(statement, (*fields.values(), actor_id, group_id))
        self._replace_links(group_id, values)
        return self.get(group_id)


class PostgresGroupUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.groups = PostgresGroupRepository(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresGroupUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
