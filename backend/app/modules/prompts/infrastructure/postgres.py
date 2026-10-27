"""Adaptador PostgreSQL de Prompts con versiones append-only y default atómico."""

from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter
from app.modules.prompts.application.ports import DefaultCollision, Prompt

FIELDS = ("p.id,p.tipo,r.codigo AS red,p.nombre,p.contenido,p.por_defecto,p.version_actual,"
          "p.estado_id,p.creado_en,p.creado_por,p.actualizado_en,p.actualizado_por")
FROM = "cfg.prompt p LEFT JOIN cat.red r ON r.id=p.red_id"
EDITABLE = frozenset({"tipo", "nombre", "contenido", "por_defecto", "estado_id"})


class PostgresPromptRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _red_id(self, network: str | None) -> int | None:
        if network is None:
            return None
        row = self.conn.execute("SELECT id FROM cat.red WHERE codigo=%s", (network,)).fetchone()
        if row is None:
            raise ValueError("Red no admitida")
        return row["id"]

    def list(self, query: str, state: str, kind: str | None, network: str | None,
             after_id: int | None, limit: int) -> tuple[int, list[Prompt]]:
        clauses = [{"vigentes": "p.estado_id<>-1", "activos": "p.estado_id=1", "inactivos": "p.estado_id=0", "eliminados": "p.estado_id=-1"}[state]]
        args: list[object] = []
        if query:
            clauses.append("(p.nombre ILIKE %s OR p.contenido ILIKE %s)")
            args.extend((f"%{query}%", f"%{query}%"))
        if kind:
            clauses.append("p.tipo=%s")
            args.append(kind)
        if network == "_":
            clauses.append("p.red_id IS NULL")
        elif network:
            clauses.append("r.codigo=%s")
            args.append(network)
        total = self.conn.execute(f"SELECT count(*) AS n FROM {FROM} WHERE {' AND '.join(clauses)}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("p.id>%s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM {FROM} WHERE {' AND '.join(clauses)} ORDER BY p.id LIMIT %s",
            (*args, limit),
        ).fetchall()
        return total, rows

    def get(self, prompt_id: int, *, for_update: bool = False) -> Prompt | None:
        return self.conn.execute(
            f"SELECT {FIELDS} FROM {FROM} WHERE p.id=%s" + (" FOR UPDATE OF p" if for_update else ""),
            (prompt_id,),
        ).fetchone()

    def lock_default_scope(self, kind: str, network: str | None) -> None:
        # Todos los escritores de un default toman este candado antes de bloquear filas.
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                          (f"syntra:prompt:{kind}:{network or '_'}",))

    def demote_default(self, kind: str, network: str | None, exclude_id: int | None,
                       actor_id: int) -> list[tuple[Prompt, Prompt]]:
        red_id = self._red_id(network)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM {FROM} WHERE p.tipo=%s AND p.red_id IS NOT DISTINCT FROM %s::smallint "
            "AND p.por_defecto AND p.estado_id=1 AND (%s::int IS NULL OR p.id<>%s::int) FOR UPDATE OF p",
            (kind, red_id, exclude_id, exclude_id),
        ).fetchall()
        demoted = []
        for before in rows:
            after = self.update(before["id"], {"por_defecto": False}, actor_id)
            demoted.append((before, after))
        return demoted

    def create(self, values: Prompt, actor_id: int) -> Prompt:
        red_id = self._red_id(values.get("red"))
        try:
            row = self.conn.execute(
                "INSERT INTO cfg.prompt(tipo,red_id,nombre,por_defecto,contenido,estado_id,creado_por,actualizado_por) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (values["tipo"], red_id, values["nombre"], values.get("por_defecto", False),
                 values["contenido"], values.get("estado_id", 1), actor_id, actor_id),
            ).fetchone()
        except UniqueViolation:
            raise DefaultCollision from None
        self.conn.execute(
            "INSERT INTO cfg.prompt_version(prompt_id,version,contenido,creado_por) VALUES (%s,1,%s,%s)",
            (row["id"], values["contenido"], actor_id),
        )
        return self.get(row["id"])

    def update(self, prompt_id: int, values: Prompt, actor_id: int) -> Prompt:
        before = self.get(prompt_id)
        fields = {key: value for key, value in values.items() if key in EDITABLE}
        if "red" in values:
            fields["red_id"] = self._red_id(values["red"])
        content_changed = "contenido" in fields and fields["contenido"] != before["contenido"]
        if content_changed:
            fields["version_actual"] = before["version_actual"] + 1
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields]
        assignments.extend((sql.SQL("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"),
                            sql.SQL("actualizado_por=%s")))
        statement = sql.SQL("UPDATE cfg.prompt SET {} WHERE id=%s RETURNING id").format(sql.SQL(",").join(assignments))
        try:
            self.conn.execute(statement, (*fields.values(), actor_id, prompt_id))
        except UniqueViolation:
            raise DefaultCollision from None
        if content_changed:
            self.conn.execute(
                "INSERT INTO cfg.prompt_version(prompt_id,version,contenido,creado_por) VALUES (%s,%s,%s,%s)",
                (prompt_id, fields["version_actual"], fields["contenido"], actor_id),
            )
        return self.get(prompt_id)

    def versions(self, prompt_id: int) -> list[dict]:
        return self.conn.execute(
            "SELECT prompt_id,version,contenido,creado_en,creado_por FROM cfg.prompt_version "
            "WHERE prompt_id=%s ORDER BY version DESC",
            (prompt_id,),
        ).fetchall()


class PostgresPromptUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.prompts = PostgresPromptRepository(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresPromptUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
