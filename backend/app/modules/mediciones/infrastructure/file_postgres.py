"""Persistencia PostgreSQL de reservas, cargas y tareas de archivos."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class PostgresMeasurementFileRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def visible_measurement(self, measurement_id: int, actor_id: int,
                            global_access: bool) -> dict | None:
        return self.conn.execute(
            "SELECT m.id,m.cuenta_id,m.estado_id FROM med.medicion m WHERE m.id=%s AND m.estado_id<>-1 "
            "AND (%s OR EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v "
            "WHERE v.cuenta_id=m.cuenta_id AND v.usuario_id=%s))",
            (measurement_id, global_access, actor_id),
        ).fetchone()

    def file_source_active(self, measurement_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM med.medicion_fuente mf JOIN cat.origen o ON o.id=mf.origen_id "
            "WHERE mf.medicion_id=%s AND o.codigo='archivo' AND mf.activo", (measurement_id,),
        ).fetchone() is not None

    def active_format(self, format_id: str) -> dict | None:
        return self.conn.execute(
            "SELECT f.id,f.extensiones,EXISTS (SELECT 1 FROM cfg.formato_columna fc "
            "WHERE fc.formato_id=f.id) AS mapeado FROM cfg.formato_archivo f "
            "WHERE f.id=%s AND f.estado_id=1", (format_id,),
        ).fetchone()

    def insert_file(self, measurement_id: int, name: str, format_id: str, key: str,
                    size: int, actor_id: int) -> dict:
        return self.conn.execute(
            "INSERT INTO med.archivo(medicion_id,nombre,formato_id,s3_bucket,s3_key,tamano_bytes,subido_por) "
            "VALUES (%s,%s,%s,'local',%s,%s,%s) RETURNING id,subido_en",
            (measurement_id, name, format_id, key, size, actor_id),
        ).fetchone()

    def locked_file(self, file_id: int, actor_id: int, global_access: bool) -> dict | None:
        return self.conn.execute(
            "SELECT a.id,a.medicion_id,a.nombre,a.formato_id,a.s3_bucket,a.s3_key,a.tamano_bytes,a.sha256,"
            "a.estado,a.subido_en,m.cuenta_id FROM med.archivo a JOIN med.medicion m ON m.id=a.medicion_id "
            "WHERE a.id=%s AND m.estado_id<>-1 AND (%s OR EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v "
            "WHERE v.cuenta_id=m.cuenta_id AND v.usuario_id=%s)) FOR UPDATE OF a",
            (file_id, global_access, actor_id),
        ).fetchone()

    def file(self, file_id: int, actor_id: int, global_access: bool) -> dict | None:
        return self.conn.execute(
            "SELECT a.id,a.medicion_id,a.nombre,a.formato_id,a.s3_bucket,a.s3_key,a.tamano_bytes,a.sha256,"
            "a.estado,a.subido_en,m.cuenta_id FROM med.archivo a JOIN med.medicion m ON m.id=a.medicion_id "
            "WHERE a.id=%s AND m.estado_id<>-1 AND (%s OR EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v "
            "WHERE v.cuenta_id=m.cuenta_id AND v.usuario_id=%s))",
            (file_id, global_access, actor_id),
        ).fetchone()

    def finish_upload(self, file_id: int, size: int, digest: bytes) -> dict | None:
        # El índice ux_archivo_hash resuelve la carrera entre subidas simultáneas.
        # El savepoint permite consultar el archivo ganador tras UniqueViolation.
        try:
            with self.conn.transaction():
                self.conn.execute("UPDATE med.archivo SET tamano_bytes=%s,sha256=%s WHERE id=%s",
                                  (size, digest, file_id))
        except psycopg.errors.UniqueViolation:
            duplicate = self.duplicate_file_for_upload(file_id, digest)
            if duplicate is None:
                raise
            return duplicate
        return None

    def duplicate_file(self, measurement_id: int, digest: bytes,
                       exclude_id: int | None = None) -> dict | None:
        return self.conn.execute(
            "SELECT a.id AS archivo_id,a.estado AS archivo_estado,p.id AS proceso_id,"
            "p.estado AS proceso_estado FROM med.archivo a "
            "LEFT JOIN LATERAL (SELECT t.proceso_id FROM prc.proceso_tarea t "
            "WHERE t.clave='archivo:'||a.id::text ORDER BY t.id DESC LIMIT 1) task ON true "
            "LEFT JOIN prc.proceso p ON p.id=task.proceso_id "
            "WHERE a.medicion_id=%s AND a.sha256=%s AND a.estado<>'error' "
            "AND (%s::bigint IS NULL OR a.id<>%s) ORDER BY a.id DESC LIMIT 1",
            (measurement_id, digest, exclude_id, exclude_id),
        ).fetchone()

    def duplicate_file_for_upload(self, file_id: int, digest: bytes) -> dict | None:
        row = self.conn.execute("SELECT medicion_id FROM med.archivo WHERE id=%s", (file_id,)).fetchone()
        return self.duplicate_file(row["medicion_id"], digest, file_id) if row else None

    def list_files(self, measurement_id: int, limit: int,
                   before: tuple[datetime, int] | None) -> list[dict]:
        return self.conn.execute(
            "SELECT a.id,a.nombre,a.formato_id,f.nombre AS formato_nombre,a.tamano_bytes,a.filas_leidas,a.filas_validas,"
            "a.filas_rechazadas,a.estado,a.subido_por,u.nombre AS subido_por_nombre,a.subido_en,"
            "(SELECT t.proceso_id FROM prc.proceso_tarea t JOIN prc.proceso p ON p.id=t.proceso_id "
            "WHERE p.medicion_id=a.medicion_id AND p.tipo='carga_archivo' "
            "AND t.clave='archivo:'||a.id::text ORDER BY t.id DESC LIMIT 1) AS proceso_id "
            "FROM med.archivo a LEFT JOIN seg.usuario u ON u.id=a.subido_por "
            "LEFT JOIN cfg.formato_archivo f ON f.id=a.formato_id "
            "WHERE a.medicion_id=%s AND a.sha256 IS NOT NULL "
            "AND (%s::timestamptz IS NULL OR (a.subido_en,a.id)<(%s,%s)) "
            "ORDER BY a.subido_en DESC,a.id DESC LIMIT %s",
            (measurement_id, before[0] if before else None,
             before[0] if before else None, before[1] if before else None, limit),
        ).fetchall()

    def list_lots(self, measurement_id: int, limit: int,
                  before: tuple[datetime, int] | None, origin: str | None) -> list[dict]:
        return self.conn.execute(
            "SELECT e.id,o.codigo AS origen,r.codigo AS red,e.scraper_id,e.archivo_id,e.detalle,"
            "e.post AS al_incorporar,e.n_leidos,e.n_nuevos,e.n_duplicados,e.n_rechazados,"
            "e.proceso_id,e.creado_en,t.estado,t.iniciado_en,t.finalizado_en,"
            "CASE WHEN t.iniciado_en IS NOT NULL AND t.finalizado_en IS NOT NULL "
            "THEN floor(extract(epoch FROM (t.finalizado_en-t.iniciado_en))*1000)::bigint "
            "ELSE NULL END AS duracion_ms "
            "FROM dat.ejecucion e JOIN cat.origen o ON o.id=e.origen_id "
            "LEFT JOIN cat.red r ON r.id=e.red_id "
            "LEFT JOIN prc.proceso_tarea t ON t.id=e.tarea_id "
            "WHERE e.medicion_id=%s AND (%s::text IS NULL OR o.codigo=%s) "
            "AND (%s::timestamptz IS NULL OR (e.creado_en,e.id)<(%s,%s)) "
            "ORDER BY e.creado_en DESC,e.id DESC LIMIT %s",
            (measurement_id, origin, origin, before[0] if before else None,
             before[0] if before else None, before[1] if before else None, limit),
        ).fetchall()

    def enqueue(self, measurement: dict, file_ids: list[int], actor_id: int,
                idempotency_key: str, options: dict[str, bool] | None,
                mode: str = "upsert") -> dict[str, Any]:
        if not self.file_source_active(measurement["id"]):
            raise ValueError("La fuente de archivos no está activa en la medición")
        key = "carga-archivo:" + idempotency_key
        # Serializa solicitudes concurrentes de la misma clave sin requerir
        # UPDATE sobre toda prc.proceso. El índice único conserva la garantía.
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
        previous = self.conn.execute(
            "SELECT id,medicion_id,opciones,estado FROM prc.proceso WHERE idempotencia=%s", (key,),
        ).fetchone()
        normalized = sorted(file_ids)
        if previous is not None:
            old = previous["opciones"] or {}
            # El modo de carga vive en opciones.modo (upsert/reemplazar); es distinto
            # de prc.proceso.modo (manual/automatico), que indica el disparo.
            if (previous["medicion_id"] != measurement["id"] or old.get("archivo_ids") != normalized
                    or old.get("al_incorporar") != options or (old.get("modo") or "upsert") != mode):
                raise ValueError("La clave de idempotencia ya pertenece a otra solicitud")
            return {"proceso_id": previous["id"], "estado": previous["estado"]}
        process = self.conn.execute(
            "INSERT INTO prc.proceso(medicion_id,cuenta_id,tipo,modo,estado,total,creado_por,idempotencia,opciones) "
            "VALUES (%s,%s,'carga_archivo','manual','en_cola',%s,%s,%s,%s) RETURNING id",
            (measurement["id"], measurement["cuenta_id"], len(file_ids), actor_id, key,
             Jsonb({"archivo_ids": normalized, "al_incorporar": options, "modo": mode})),
        ).fetchone()
        for file_id in normalized:
            self.conn.execute(
                "INSERT INTO prc.proceso_tarea(proceso_id,clave,tipo,cola,payload) "
                "VALUES (%s,%s,'carga_archivo','q.ingesta',%s)",
                (process["id"], f"archivo:{file_id}", Jsonb({"archivo_id": file_id,
                  "medicion_id": measurement["id"], "cuenta_id": measurement["cuenta_id"]})),
            )
        return {"proceso_id": process["id"], "estado": "en_cola"}

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()
