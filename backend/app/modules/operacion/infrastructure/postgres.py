"""Consultas PostgreSQL de solo lectura para workers, colas y procesos propios."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg


class PostgresOperationsReader:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def queues(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """WITH monitored(cola) AS (VALUES ('q.notificaciones'::text), ('q.reportes'::text),
                                           ('q.ingesta'::text)),
               task_stats AS (
                 SELECT cola,
                        count(*) FILTER (WHERE t.estado='en_cola')::int AS en_cola,
                        count(*) FILTER (WHERE t.estado='en_ejecucion')::int AS en_ejecucion,
                        count(*) FILTER (WHERE t.estado='error')::int AS con_error,
                        greatest(0, extract(epoch FROM (now()-min(p.creado_en)
                          FILTER (WHERE t.estado='en_cola' AND t.disponible_en<=now())))::int) AS mas_antigua_s
                   FROM prc.proceso_tarea t
                   LEFT JOIN prc.proceso p ON p.id=t.proceso_id
                  WHERE (t.cola,t.tipo) IN (('q.notificaciones','correo_acceso'),
                                            ('q.reportes','auditoria_exportar'),
                                            ('q.ingesta','carga_archivo'))
                  GROUP BY cola
               ), live_workers AS (
                 SELECT q.cola, count(w.id)::int AS workers
                   FROM monitored q
                   LEFT JOIN ops.worker w ON q.cola=ANY(w.colas) AND w.latido >= now()-interval '45 seconds'
                  GROUP BY q.cola
               )
               SELECT q.cola, coalesce(s.en_cola,0)::int AS en_cola,
                      coalesce(s.en_ejecucion,0)::int AS en_ejecucion,
                      coalesce(s.con_error,0)::int AS con_error,
                      coalesce(s.mas_antigua_s,0)::int AS mas_antigua_s,
                      w.workers
                 FROM monitored q LEFT JOIN task_stats s USING (cola)
                 JOIN live_workers w USING (cola) ORDER BY q.cola"""
        ).fetchall()
        return [dict(row) for row in rows]

    def workers(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT id,servidor,colas,iniciado_en,latido,tareas_en_curso,
                      (latido >= now()-interval '45 seconds') AS vivo
                 FROM ops.worker
                WHERE colas && ARRAY['q.notificaciones','q.reportes','q.ingesta']::text[]
                ORDER BY colas,id"""
        ).fetchall()
        return [dict(row) for row in rows]

    def _process_where(self, owner_id: int, filters: dict[str, Any], visible_types: tuple[str, ...]) -> tuple[str, list[Any]]:
        where = """creado_por=%s
                  AND ((tipo='correo_acceso') OR (tipo='exportacion' AND opciones->>'kind'='auditoria')
                       OR (tipo='preparar_medicion' AND opciones->>'kind'='preparacion_medicion')
                       OR (tipo='carga_scraper'))
                  AND tipo = ANY(%s)
                  AND creado_en >= now()-interval '7 days' AND creado_en <= now()
                  AND (%s::text IS NULL OR tipo=%s)
                  AND (%s::text IS NULL OR estado=%s)
                  AND (%s::text IS NULL OR modo=%s)
                  AND (%s::int IS NULL OR medicion_id=%s)"""
        params: list[Any] = [owner_id, list(visible_types), filters.get("tipo"), filters.get("tipo"), filters.get("estado"), filters.get("estado"),
                             filters.get("modo"), filters.get("modo"), filters.get("medicion_id"), filters.get("medicion_id")]
        return where, params

    def processes(self, owner_id: int, filters: dict[str, Any], after: tuple[datetime, int] | None,
                  limit: int, visible_types: tuple[str, ...]) -> list[dict[str, Any]]:
        where, params = self._process_where(owner_id, filters, visible_types)
        cursor_sql = ""
        if after is not None:
            cursor_sql = " AND (creado_en,id) < (%s,%s)"
            params.extend(after)
        params.append(limit)
        rows = self.conn.execute(
            """SELECT id,medicion_id,tipo,modo,estado,progreso,total,procesados,ok,errores,
                      creado_en,iniciado_en,finalizado_en,duracion_ms,sla_ms,creado_por
                 FROM prc.proceso
                WHERE """ + where + cursor_sql + " ORDER BY creado_en DESC,id DESC LIMIT %s",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def process_statistics(self, owner_id: int, visible_types: tuple[str, ...]) -> dict[str, Any]:
        summary = self.conn.execute(
            """WITH own AS (
                   SELECT id,tipo,estado,finalizado_en,duracion_ms,sla_ms,procesados
                     FROM prc.proceso
                    WHERE creado_por=%s AND tipo=ANY(%s)
                      AND ((tipo='correo_acceso') OR (tipo='exportacion' AND opciones->>'kind'='auditoria')
                           OR (tipo='preparar_medicion' AND opciones->>'kind'='preparacion_medicion')
                           OR (tipo='carga_scraper'))
                 ), recent AS (
                   SELECT id,duracion_ms,sla_ms FROM own
                    WHERE finalizado_en >= now()-interval '30 days' AND finalizado_en <= now()
                      AND duracion_ms IS NOT NULL AND estado <> 'cancelado'
                 )
                 SELECT count(*) FILTER (WHERE p.estado IN ('en_cola','en_ejecucion'))::int AS en_ejecucion_o_en_cola,
                        count(*) FILTER (WHERE p.estado='completado'
                          AND p.finalizado_en >= now()-interval '24 hours' AND p.finalizado_en <= now())::int AS completados_24h,
                        coalesce(sum(p.procesados) FILTER (WHERE p.estado='completado'
                          AND p.finalizado_en >= now()-interval '24 hours' AND p.finalizado_en <= now()),0)::bigint AS registros_procesados_24h,
                        count(*) FILTER (WHERE p.estado IN ('error','advertencia')
                          AND p.finalizado_en >= now()-interval '7 days' AND p.finalizado_en <= now())::int AS errores_advertencias_7d,
                        round(avg(r.duracion_ms))::bigint AS duracion_promedio_ms,
                        max(r.duracion_ms)::bigint AS duracion_maxima_ms,
                        round(100.0 * count(*) FILTER (WHERE r.sla_ms IS NOT NULL AND r.duracion_ms <= r.sla_ms)
                          / nullif(count(*) FILTER (WHERE r.sla_ms IS NOT NULL),0),1) AS sla_cumplimiento_pct
                   FROM own p LEFT JOIN recent r USING (id)""",
            (owner_id, list(visible_types)),
        ).fetchone()
        recent = self.conn.execute(
            """SELECT id,tipo,estado,duracion_ms,sla_ms,finalizado_en
                 FROM prc.proceso
                WHERE creado_por=%s AND tipo=ANY(%s)
                  AND ((tipo='correo_acceso') OR (tipo='exportacion' AND opciones->>'kind'='auditoria')
                       OR (tipo='preparar_medicion' AND opciones->>'kind'='preparacion_medicion')
                       OR (tipo='carga_scraper'))
                  AND finalizado_en IS NOT NULL AND finalizado_en <= now()
                  AND duracion_ms IS NOT NULL AND estado <> 'cancelado'
                ORDER BY finalizado_en DESC,id DESC LIMIT 36""",
            (owner_id, list(visible_types)),
        ).fetchall()
        return {**dict(summary), "ultimas_duraciones": [dict(row) for row in reversed(recent)]}

    def process(self, process_id: int) -> dict[str, Any] | None:
        return self.conn.execute(
            """SELECT id,tipo,creado_por,opciones,medicion_id,cuenta_id
                 FROM prc.proceso WHERE id=%s""", (process_id,),
        ).fetchone()

    def measurement_process_visible(self, process_id: int, owner_id: int, global_access: bool) -> bool:
        return bool(self.conn.execute(
            "SELECT 1 FROM prc.proceso p JOIN med.medicion m ON m.id=p.medicion_id "
            "WHERE p.id=%s AND p.creado_por=%s AND (%s OR EXISTS ("
            "SELECT 1 FROM seg.v_usuario_cuenta v WHERE v.cuenta_id=m.cuenta_id AND v.usuario_id=%s))",
            (process_id, owner_id, global_access, owner_id),
        ).fetchone())

    def tasks(self, process_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT id,clave,tipo,estado,intentos,ok,errores,error_codigo,
                      iniciado_en,finalizado_en
                 FROM prc.proceso_tarea WHERE proceso_id=%s ORDER BY id""", (process_id,),
        ).fetchall()
        return [dict(row) for row in rows]
