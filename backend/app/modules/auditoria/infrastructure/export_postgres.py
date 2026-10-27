"""Persistencia de exportaciones y seguimiento sin exponer tareas ajenas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class PostgresExportStore:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def enqueue(self, actor_id: int, key: str, filters: dict[str, Any]) -> tuple[int, bool, str]:
        options = {"kind": "auditoria", "filters": filters, "corte": datetime.now(timezone.utc).isoformat()}
        row = self.conn.execute(
            "INSERT INTO prc.proceso(tipo,modo,opciones,creado_por,idempotencia) "
            "VALUES ('exportacion','manual',%s,%s,%s) "
            "ON CONFLICT (idempotencia) WHERE idempotencia IS NOT NULL DO NOTHING RETURNING id",
            (Jsonb(options), actor_id, key),
        ).fetchone()
        if row is None:
            existing = self.conn.execute(
                "SELECT id,creado_por,tipo,estado,opciones FROM prc.proceso WHERE idempotencia=%s", (key,),
            ).fetchone()
            return existing["id"], (existing["creado_por"] == actor_id and
                                    existing["tipo"] == "exportacion" and
                                    existing["opciones"].get("kind") == "auditoria" and
                                    existing["opciones"].get("filters") == filters), existing["estado"]
        self.conn.execute(
            "INSERT INTO prc.proceso_tarea(proceso_id,clave,tipo,cola,prioridad,payload) "
            "VALUES (%s,'auditoria','auditoria_exportar','q.reportes',1,'{}'::jsonb)", (row["id"],),
        )
        self.conn.commit()
        return row["id"], True, "en_cola"

    def get(self, process_id: int) -> dict[str, Any] | None:
        return self.conn.execute(
            "SELECT id,tipo,estado,creado_por,creado_en,iniciado_en,finalizado_en,progreso,"
            "total,procesados,ok,errores,stats,opciones FROM prc.proceso WHERE id=%s", (process_id,),
        ).fetchone()
