"""Adaptador PostgreSQL de Actores; una transacción para entidad y evento."""

from __future__ import annotations

import psycopg
from psycopg import sql

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter
from app.modules.actores.application.ports import Actor, UnknownNetwork

FIELDS = ("a.id,r.codigo AS red,a.uso,a.nombre,a.actor,a.max_registros,a.max_urls_por_corrida,"
          "a.memoria_mb,a.nota,a.estado_id,a.creado_en,a.creado_por,a.actualizado_en,a.actualizado_por")
EDITABLE = frozenset({"uso", "nombre", "actor", "max_registros", "max_urls_por_corrida",
                      "memoria_mb", "nota", "estado_id"})


class PostgresActorRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _red_id(self, code: str) -> int:
        row = self.conn.execute("SELECT id FROM cat.red WHERE codigo=%s", (code,)).fetchone()
        if row is None:
            raise UnknownNetwork
        return row["id"]

    def list(self, query: str, state: str, after_id: int | None, limit: int) -> tuple[int, list[Actor]]:
        clauses = [{"vigentes": "a.estado_id<>-1", "activos": "a.estado_id=1",
                    "inactivos": "a.estado_id=0", "eliminados": "a.estado_id=-1"}[state]]
        args: list[object] = []
        if query:
            clauses.append("(a.nombre ILIKE %s OR a.actor ILIKE %s)")
            args.extend((f"%{query}%", f"%{query}%"))
        where = " AND ".join(clauses)
        total = self.conn.execute(
            f"SELECT count(*) AS n FROM cfg.actor_scraping a WHERE {where}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("a.id>%s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM cfg.actor_scraping a JOIN cat.red r ON r.id=a.red_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY a.id LIMIT %s",
            (*args, limit),
        ).fetchall()
        return total, rows

    def get(self, actor_id: int, *, for_update: bool = False) -> Actor | None:
        return self.conn.execute(
            f"SELECT {FIELDS} FROM cfg.actor_scraping a JOIN cat.red r ON r.id=a.red_id "
            f"WHERE a.id=%s" + (" FOR UPDATE OF a" if for_update else ""),
            (actor_id,),
        ).fetchone()

    def create(self, values: Actor, actor_id: int) -> Actor:
        red_id = self._red_id(values["red"])
        row = self.conn.execute(
            "INSERT INTO cfg.actor_scraping(red_id,uso,nombre,actor,max_registros,max_urls_por_corrida,"
            "memoria_mb,nota,estado_id,creado_por,actualizado_por) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (red_id, values.get("uso", "busqueda"), values["nombre"], values["actor"],
             values.get("max_registros", 1000), values.get("max_urls_por_corrida", 1000),
             values.get("memoria_mb", 4096), values.get("nota"), values.get("estado_id", 1),
             actor_id, actor_id),
        ).fetchone()
        return self.get(row["id"])

    def update(self, actor_id: int, values: Actor, user_id: int) -> Actor:
        assignments = []
        params: list[object] = []
        if "red" in values:
            assignments.append(sql.SQL("red_id=%s"))
            params.append(self._red_id(values["red"]))
        for key in (key for key in values if key in EDITABLE):
            assignments.append(sql.SQL("{}=%s").format(sql.Identifier(key)))
            params.append(values[key])
        assignments.extend((
            sql.SQL("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"),
            sql.SQL("actualizado_por=%s")))
        params.append(user_id)
        statement = sql.SQL("UPDATE cfg.actor_scraping SET {} WHERE id=%s RETURNING id").format(
            sql.SQL(",").join(assignments))
        self.conn.execute(statement, (*params, actor_id))
        return self.get(actor_id)


class PostgresActorUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.actors = PostgresActorRepository(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresActorUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
