"""Adaptador PostgreSQL de Países; una transacción para entidad y evento."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter
from app.modules.paises.application.ports import Country, DuplicateCode

FIELDS = "id,nombre,codigo,idioma,estado_id,creado_en,creado_por,actualizado_en,actualizado_por"
EDITABLE = frozenset({"nombre", "codigo", "idioma", "estado_id"})


class PostgresCountryRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list(self, query: str, state: str, after_id: int | None, limit: int) -> tuple[int, list[Country]]:
        clauses = [{"vigentes": "estado_id<>-1", "activos": "estado_id=1", "inactivos": "estado_id=0", "eliminados": "estado_id=-1"}[state]]
        args: list[object] = []
        if query:
            clauses.append("(nombre ILIKE %s OR codigo ILIKE %s)")
            args.extend((f"%{query}%", f"%{query}%"))
        total = self.conn.execute(f"SELECT count(*) AS n FROM cfg.pais WHERE {' AND '.join(clauses)}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("id>%s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM cfg.pais WHERE {' AND '.join(clauses)} ORDER BY id LIMIT %s",
            (*args, limit),
        ).fetchall()
        for row in rows:
            row["codigo"] = row["codigo"].strip()
        return total, rows

    def get(self, country_id: int, *, for_update: bool = False) -> Country | None:
        row = self.conn.execute(
            f"SELECT {FIELDS} FROM cfg.pais WHERE id=%s" + (" FOR UPDATE" if for_update else ""),
            (country_id,),
        ).fetchone()
        if row:
            row["codigo"] = row["codigo"].strip()
        return row

    def code_exists(self, code: str, exclude_id: int | None = None) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM cfg.pais WHERE codigo=%s AND estado_id<>-1 "
            "AND (%s::int IS NULL OR id<>%s::int)) AS existe",
            (code, exclude_id, exclude_id),
        ).fetchone()["existe"]

    def create(self, values: Country, actor_id: int) -> Country:
        try:
            row = self.conn.execute(
                f"INSERT INTO cfg.pais(nombre,codigo,idioma,estado_id,creado_por,actualizado_por) "
                f"VALUES (%s,%s,%s,%s,%s,%s) RETURNING {FIELDS}",
                (values["nombre"], values["codigo"], values.get("idioma", "es-419"),
                 values.get("estado_id", 1), actor_id, actor_id),
            ).fetchone()
        except UniqueViolation:
            raise DuplicateCode from None
        return self.get(row["id"])

    def update(self, country_id: int, values: Country, actor_id: int) -> Country:
        fields = {key: value for key, value in values.items() if key in EDITABLE}
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields]
        assignments.extend((sql.SQL("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"),
                            sql.SQL("actualizado_por=%s")))
        statement = sql.SQL("UPDATE cfg.pais SET {} WHERE id=%s RETURNING id").format(sql.SQL(",").join(assignments))
        try:
            self.conn.execute(statement, (*fields.values(), actor_id, country_id))
        except UniqueViolation:
            raise DuplicateCode from None
        return self.get(country_id)


class PostgresCountryUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.countries = PostgresCountryRepository(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresCountryUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
