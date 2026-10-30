"""Adaptador PostgreSQL del reparto a q.llm (FanoutPort).

Opera bajo el rol del worker de ingesta (``svc_ingesta``), que ya tiene
INSERT/UPDATE sobre el esquema ``prc`` y lectura de ``dat``. El tamaño de ventana
sale de ``ops.parametro('llm.registros_por_tarea')`` con un respaldo en código.
"""

from __future__ import annotations

from typing import Callable

import psycopg
from psycopg.types.json import Jsonb

CHUNK_SIZE_DEFAULT = 500
PARAM_CHUNK_SIZE = "llm.registros_por_tarea"


def chunk_size(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT valor FROM ops.parametro WHERE clave=%s", (PARAM_CHUNK_SIZE,)).fetchone()
    try:
        valor = int(row["valor"]) if row else CHUNK_SIZE_DEFAULT
    except (TypeError, ValueError):
        valor = CHUNK_SIZE_DEFAULT
    return valor if 1 <= valor <= 100_000 else CHUNK_SIZE_DEFAULT


class PostgresFanout:
    def __init__(self, connect: Callable[[], psycopg.Connection]):
        self._connect = connect

    def source_proceso(self, proceso_id: int) -> dict | None:
        """Solo reparte una carga ya completada; devuelve sus opciones al incorporar.

        Archivos/Meltwater/manual guardan las opciones en ``proceso.opciones.al_incorporar``;
        el scraper (Apify) las tiene en ``med.scraper`` (post_*), así que se resuelven allí.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id,medicion_id,cuenta_id,creado_por,tipo,opciones,scraper_id FROM prc.proceso "
                "WHERE id=%s AND tipo IN ('carga_archivo','carga_meltwater','carga_manual','carga_scraper') "
                "AND estado='completado'", (proceso_id,),
            ).fetchone()
            if row is None or row["cuenta_id"] is None or row["medicion_id"] is None:
                return None
            if row["tipo"] == "carga_scraper":
                sc = conn.execute(
                    "SELECT post_incorporar,post_relevancia,post_sentimiento,post_clusters,post_bots "
                    "FROM med.scraper WHERE id=%s", (row["scraper_id"],),
                ).fetchone()
                options = {"incorporar": sc["post_incorporar"], "relevancia": sc["post_relevancia"],
                           "sentimiento": sc["post_sentimiento"], "clusters": sc["post_clusters"],
                           "bots": sc["post_bots"]} if sc else {}
            else:
                options = row["opciones"].get("al_incorporar") or {}
            return {"id": row["id"], "medicion_id": row["medicion_id"],
                    "cuenta_id": row["cuenta_id"], "creado_por": row["creado_por"],
                    "options": options}

    def pending_stats(self, cuenta_id: int, medicion_id: int, source_id: int) -> list[dict]:
        with self._connect() as conn:
            return [
                {"periodo": row["periodo"], "min_id": row["min_id"],
                 "max_id": row["max_id"], "count": row["n"]}
                for row in conn.execute(
                    "SELECT periodo,min(registro_id) AS min_id,max(registro_id) AS max_id,count(*) AS n "
                    "FROM dat.registro_estado WHERE cuenta_id=%s AND medicion_id=%s "
                    "AND ultimo_proceso_id=%s AND incorporado AND estado_id<>-1 "
                    "AND (st_relevancia=0 OR st_sentimiento=0 OR st_embedding=0) "
                    "GROUP BY periodo ORDER BY periodo",
                    (cuenta_id, medicion_id, source_id),
                ).fetchall()
            ]

    def create_child(self, source: dict, tipo: str) -> int | None:
        """Proceso hijo encadenado a la ingesta; idempotente por 'computo:<id>'."""
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO prc.proceso(medicion_id,cuenta_id,tipo,modo,padre_id,creado_por,"
                "idempotencia,opciones) VALUES (%s,%s,%s,'automatico',%s,%s,%s,%s) "
                "ON CONFLICT (idempotencia) WHERE idempotencia IS NOT NULL DO NOTHING RETURNING id",
                (source["medicion_id"], source["cuenta_id"], tipo, source["id"],
                 source["creado_por"], f"computo:{source['id']}",
                 Jsonb({"al_incorporar": source["options"], "modo_llm": "lote"})),
            ).fetchone()
            return row["id"] if row else None

    def enqueue_chunks(self, child_id: int, cuenta_id: int, medicion_id: int,
                       tipo: str, chunks: list[dict]) -> None:
        with self._connect() as conn:
            for chunk in chunks:
                conn.execute(
                    "INSERT INTO prc.proceso_tarea(proceso_id,clave,tipo,cola,prioridad,"
                    "rango_desde,rango_hasta,payload) VALUES (%s,%s,%s,'q.llm',5,%s,%s,%s) "
                    "ON CONFLICT (proceso_id,clave) DO NOTHING",
                    (child_id, chunk["clave"], tipo, chunk["desde"], chunk["hasta"],
                     Jsonb({"periodo": chunk["periodo"], "desde": chunk["desde"],
                            "hasta": chunk["hasta"]})),
                )
            conn.execute("UPDATE prc.proceso SET total=%s,estado=CASE WHEN %s=0 THEN 'completado' "
                         "ELSE 'en_cola' END,finalizado_en=CASE WHEN %s=0 THEN now() ELSE NULL END "
                         "WHERE id=%s", (len(chunks), len(chunks), len(chunks), child_id))
