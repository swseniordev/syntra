"""Persistencia PostgreSQL de Regex y versiones append-only."""

from __future__ import annotations

import psycopg
from psycopg import sql

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter
from app.modules.regex.application.ports import Regex

FIELDS = "id,nombre,condicion,flags,texto_prueba,descripcion,version,estado_id,creado_en,creado_por,actualizado_en,actualizado_por"
EDITABLE = frozenset({"nombre", "condicion", "flags", "texto_prueba", "descripcion", "estado_id"})


class PostgresRegexRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list(self, query: str, state: str, after_id: int | None, limit: int) -> tuple[int, list[Regex]]:
        clauses = [{"vigentes": "estado_id<>-1", "activos": "estado_id=1", "inactivos": "estado_id=0", "eliminados": "estado_id=-1"}[state]]
        args: list[object] = []
        if query:
            clauses.append("(nombre ILIKE %s OR condicion ILIKE %s OR descripcion ILIKE %s)")
            args.extend((f"%{query}%",) * 3)
        total = self.conn.execute(f"SELECT count(*) AS n FROM cfg.regex WHERE {' AND '.join(clauses)}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("id>%s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM cfg.regex WHERE {' AND '.join(clauses)} ORDER BY id LIMIT %s",
            (*args, limit),
        ).fetchall()
        return total, rows

    def get(self, regex_id: int, *, for_update: bool = False) -> Regex | None:
        return self.conn.execute(
            f"SELECT {FIELDS} FROM cfg.regex WHERE id=%s" + (" FOR UPDATE" if for_update else ""),
            (regex_id,),
        ).fetchone()

    def lock_name(self, name: str) -> None:
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"syntra:regex:{name.casefold()}",))

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM cfg.regex WHERE lower(nombre)=lower(%s) AND estado_id<>-1 "
            "AND (%s::int IS NULL OR id<>%s::int)) AS existe",
            (name, exclude_id, exclude_id),
        ).fetchone()["existe"]

    def create(self, values: Regex, actor_id: int) -> Regex:
        identifier = self.conn.execute(
            "INSERT INTO cfg.regex(nombre,condicion,flags,texto_prueba,descripcion,estado_id,creado_por,actualizado_por) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (values["nombre"], values["condicion"], values["flags"], values["texto_prueba"],
             values.get("descripcion"), values.get("estado_id", 1), actor_id, actor_id),
        ).fetchone()["id"]
        self.conn.execute(
            "INSERT INTO cfg.regex_version(regex_id,version,condicion,flags,creado_por) VALUES (%s,1,%s,%s,%s)",
            (identifier, values["condicion"], values["flags"], actor_id),
        )
        return self.get(identifier)

    def update(self, regex_id: int, values: Regex, actor_id: int) -> Regex:
        before = self.get(regex_id)
        fields = {key: value for key, value in values.items() if key in EDITABLE}
        pattern_changed = any(key in fields and fields[key] != before[key] for key in ("condicion", "flags"))
        if pattern_changed:
            fields["version"] = before["version"] + 1
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields]
        assignments.extend((sql.SQL("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"),
                            sql.SQL("actualizado_por=%s")))
        statement = sql.SQL("UPDATE cfg.regex SET {} WHERE id=%s RETURNING id").format(sql.SQL(",").join(assignments))
        self.conn.execute(statement, (*fields.values(), actor_id, regex_id))
        if pattern_changed:
            self.conn.execute(
                "INSERT INTO cfg.regex_version(regex_id,version,condicion,flags,creado_por) VALUES (%s,%s,%s,%s,%s)",
                (regex_id, fields["version"], fields.get("condicion", before["condicion"]),
                 fields.get("flags", before["flags"]), actor_id),
            )
        return self.get(regex_id)

    def versions(self, regex_id: int) -> list[dict]:
        return self.conn.execute(
            "SELECT regex_id,version,condicion,flags,creado_en,creado_por FROM cfg.regex_version "
            "WHERE regex_id=%s ORDER BY version DESC", (regex_id,),
        ).fetchall()


class PostgresRegexUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.regex = PostgresRegexRepository(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresRegexUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
