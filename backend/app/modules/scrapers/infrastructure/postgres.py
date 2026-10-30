"""Adaptador PostgreSQL de ejecución de Scrapers; proceso y tareas en una transacción."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter
from app.modules.scrapers.application.ports import Row


class PostgresScraperRuns:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list_for_measurement(self, medicion_id: int) -> list[Row]:
        return self.conn.execute(
            "SELECT s.id,s.nombre,s.medicion_id,s.estado_id,s.ejecucion_auto,s.gn_activo,"
            "s.frecuencia_min,s.proxima_ejecucion,"
            "ARRAY(SELECT r.codigo FROM med.scraper_red sr JOIN cat.red r ON r.id=sr.red_id "
            "WHERE sr.scraper_id=s.id AND sr.activo ORDER BY r.id) AS redes "
            "FROM med.scraper s WHERE s.medicion_id=%s AND s.estado_id<>-1 ORDER BY s.id",
            (medicion_id,),
        ).fetchall()

    def load(self, scraper_id: int) -> Row | None:
        return self.conn.execute(
            "SELECT s.id,s.nombre,s.medicion_id,s.estado_id,s.gn_activo,s.gn_registros,"
            "s.post_incorporar,s.post_relevancia,s.post_sentimiento,s.post_clusters,s.post_bots,"
            "m.cuenta_id FROM med.scraper s JOIN med.medicion m ON m.id=s.medicion_id "
            "WHERE s.id=%s",
            (scraper_id,),
        ).fetchone()

    def active_reds(self, scraper_id: int) -> list[Row]:
        return self.conn.execute(
            "SELECT r.codigo,sr.registros FROM med.scraper_red sr JOIN cat.red r ON r.id=sr.red_id "
            "WHERE sr.scraper_id=%s AND sr.activo ORDER BY r.id",
            (scraper_id,),
        ).fetchall()

    def countries(self, scraper_id: int) -> list[str]:
        return [row["codigo"] for row in self.conn.execute(
            "SELECT p.codigo FROM med.scraper_pais sp JOIN cfg.pais p ON p.id=sp.pais_id "
            "WHERE sp.scraper_id=%s ORDER BY p.id", (scraper_id,),
        ).fetchall()]

    def existing_process(self, idempotency: str) -> Row | None:
        return self.conn.execute(
            "SELECT id,estado FROM prc.proceso WHERE idempotencia=%s", (idempotency,),
        ).fetchone()

    def create_process(self, scraper: Row, options: dict[str, Any], total: int,
                        idempotency: str, actor_id: int) -> int:
        row = self.conn.execute(
            "INSERT INTO prc.proceso(medicion_id,cuenta_id,tipo,modo,estado,prioridad,scraper_id,"
            "opciones,total,creado_por,idempotencia) "
            "VALUES (%s,%s,'carga_scraper','manual','en_cola',5,%s,%s,%s,%s,%s) RETURNING id",
            (scraper["medicion_id"], scraper["cuenta_id"], scraper["id"], Jsonb(options),
             total, actor_id, idempotency),
        ).fetchone()
        return row["id"]

    def add_task(self, process_id: int, clave: str, tipo: str, objetivo: int) -> None:
        self.conn.execute(
            "INSERT INTO prc.proceso_tarea(proceso_id,clave,tipo,cola,objetivo,payload) "
            "VALUES (%s,%s,%s,'q.apify',%s,%s)",
            (process_id, clave, tipo, objetivo, Jsonb({})),
        )


class PostgresScraperUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.runs = PostgresScraperRuns(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresScraperUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
