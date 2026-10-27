"""Cola durable q.ingesta y persistencia de lotes Talkwalker en PostgreSQL."""

from __future__ import annotations

from datetime import datetime
import logging
import time
from threading import Event, Thread
from typing import Callable
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.application.ingest_file import IngestFile
from app.application.ingest_notice import finished_upload_notice
from app.config import WorkerSettings
from app.domain.ingest_actions import initial_ingest_state
from app.domain.tasks import ClaimedTask
from app.infrastructure.ingest_source import LocalIngestSource


QUEUE = "q.ingesta"
TYPE = "carga_archivo"
HEARTBEAT_SECONDS = 15
logger = logging.getLogger("syntra.worker.ingesta")


def ingest_policy(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        "SELECT max_intentos,backoff_base_ms,backoff_max_ms,timeout_ms "
        "FROM ops.politica_reintento WHERE operacion=%s", (TYPE,),
    ).fetchone()
    if (row is None or not 1 <= row["max_intentos"] <= 10 or row["backoff_base_ms"] < 1
            or row["backoff_max_ms"] < row["backoff_base_ms"] or row["timeout_ms"] < 1):
        raise ValueError("La política persistida de ingesta falta o es inválida")
    return row


def ingest_retry_delay(attempt: int, policy: dict) -> int | None:
    if attempt >= policy["max_intentos"]:
        return None
    return policy["backoff_base_ms"] if attempt == 1 else policy["backoff_max_ms"]


class IngestQueue:
    def __init__(self, settings: WorkerSettings,
                 connect: Callable[[], psycopg.Connection] | None = None):
        self.settings = settings
        self._connect = connect or self._database_connection
        self.source = LocalIngestSource(settings.upload_root)
        self._next_notice_scan = 0.0

    def _database_connection(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.database_host, port=self.settings.database_port,
            dbname=self.settings.database_name, user=self.settings.database_user,
            passfile=str(self.settings.database_passfile), row_factory=dict_row,
            connect_timeout=5, application_name="syntra_ingest_worker",
        )

    @staticmethod
    def _aggregate(conn: psycopg.Connection, process_id: int) -> None:
        conn.execute("SELECT id FROM prc.proceso WHERE id=%s FOR UPDATE", (process_id,))
        totals = conn.execute(
            "SELECT count(*) FILTER (WHERE estado='completado') AS ok,"
            "count(*) FILTER (WHERE estado='error') AS errors,"
            "count(*) AS total FROM prc.proceso_tarea WHERE proceso_id=%s", (process_id,),
        ).fetchone()
        done = totals["ok"] + totals["errors"]
        terminal = done == totals["total"]
        state = "error" if terminal and totals["errors"] else "completado" if terminal else "en_ejecucion"
        conn.execute(
            "UPDATE prc.proceso SET estado=%s,procesados=%s,ok=%s,errores=%s,"
            "progreso=CASE WHEN total=0 THEN 100 ELSE LEAST(100,(%s*100/total)) END,"
            "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s",
            (state, done, totals["ok"], totals["errors"], done, terminal, process_id),
        )

    def recover(self) -> int:
        with self._connect() as conn:
            policy = ingest_policy(conn)
            # Una preparación terminada en error nunca habilitará la ingesta.
            # Cerrar su tarea evita que permanezca indefinidamente en cola.
            blocked = conn.execute(
                "SELECT t.id,t.proceso_id,t.payload FROM prc.proceso_tarea t "
                "JOIN prc.proceso p ON p.id=t.proceso_id "
                "WHERE t.cola=%s AND t.tipo=%s AND t.estado='en_cola' "
                "AND EXISTS (SELECT 1 FROM prc.proceso prep WHERE prep.medicion_id=p.medicion_id "
                "AND prep.tipo='preparar_medicion' AND prep.estado='error') "
                "AND NOT EXISTS (SELECT 1 FROM prc.proceso prep WHERE prep.medicion_id=p.medicion_id "
                "AND prep.tipo='preparar_medicion' AND prep.estado='completado') "
                "ORDER BY t.id FOR UPDATE OF t SKIP LOCKED",
                (QUEUE, TYPE),
            ).fetchall()
            for task in blocked:
                conn.execute(
                    "UPDATE prc.proceso_tarea SET estado='error',finalizado_en=now(),"
                    "error_codigo='preparacion_fallida',"
                    "error_mensaje='La preparación de la medición terminó en error' WHERE id=%s",
                    (task["id"],),
                )
                file_id = task["payload"].get("archivo_id")
                if type(file_id) is int:
                    conn.execute("UPDATE med.archivo SET estado='error',error='preparacion_fallida' WHERE id=%s",
                                 (file_id,))
                self._aggregate(conn, task["proceso_id"])
            tasks = conn.execute(
                "SELECT id,proceso_id,intentos,payload FROM prc.proceso_tarea "
                "WHERE cola=%s AND tipo=%s AND estado='en_ejecucion' "
                "AND (latido IS NULL OR latido<now()-(%s*interval '1 second')) "
                "ORDER BY id FOR UPDATE SKIP LOCKED",
                (QUEUE, TYPE, self.settings.lease_seconds),
            ).fetchall()
            for task in tasks:
                delay = ingest_retry_delay(task["intentos"], policy)
                terminal = delay is None
                conn.execute(
                    "UPDATE prc.proceso_tarea SET estado=%s,worker=NULL,latido=NULL,"
                    "disponible_en=now()+(%s*interval '1 millisecond'),"
                    "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,"
                    "error_codigo='worker_interrumpido',error_mensaje='Worker de ingesta interrumpido' WHERE id=%s",
                    ("error" if terminal else "en_cola", delay or 0, terminal, task["id"]),
                )
                if terminal:
                    file_id = task["payload"].get("archivo_id")
                    if type(file_id) is int:
                        conn.execute("UPDATE med.archivo SET estado='error',error='worker_interrumpido' WHERE id=%s",
                                     (file_id,))
                    self._aggregate(conn, task["proceso_id"])
                else:
                    conn.execute("UPDATE prc.proceso SET estado='en_cola' WHERE id=%s",
                                 (task["proceso_id"],))
            recovered = len(blocked) + len(tasks)
        if time.monotonic() >= self._next_notice_scan:
            self._next_notice_scan = time.monotonic() + 60
            self._notify_pending()
        return recovered

    def _notify_pending(self) -> None:
        """Recupera avisos que no se publicaron tras una caída o falta de permisos."""
        try:
            with self._connect() as conn:
                pending = conn.execute(
                    "SELECT p.id FROM prc.proceso p WHERE p.tipo=%s "
                    "AND p.estado IN ('completado','error') AND p.creado_por IS NOT NULL "
                    "AND p.creado_en>=now()-interval '7 days' "
                    "AND NOT EXISTS (SELECT 1 FROM aud.notificacion n "
                    "WHERE n.proceso_id=p.id AND n.usuario_id=p.creado_por) "
                    "ORDER BY p.id DESC LIMIT 100", (TYPE,),
                ).fetchall()
            for row in pending:
                self._notify_terminal(row["id"])
        except psycopg.Error as exc:
            logger.warning("No se pudieron recuperar avisos de ingesta; SQLSTATE=%s",
                           exc.sqlstate or "desconocido")

    def _notify_terminal(self, process_id: int) -> None:
        """El bloqueo del proceso cerca el INSERT para evitar avisos duplicados."""
        try:
            with self._connect() as conn:
                process = conn.execute(
                    "SELECT id,medicion_id,creado_por,estado FROM prc.proceso "
                    "WHERE id=%s AND tipo=%s FOR UPDATE", (process_id, TYPE),
                ).fetchone()
                if (process is None or process["estado"] not in {"completado", "error"}
                        or process["creado_por"] is None):
                    return
                exists = conn.execute(
                    "SELECT 1 FROM aud.notificacion WHERE usuario_id=%s AND proceso_id=%s LIMIT 1",
                    (process["creado_por"], process_id),
                ).fetchone()
                if exists:
                    return
                rejected = conn.execute(
                    "SELECT COALESCE(sum(a.filas_rechazadas),0) AS total "
                    "FROM prc.proceso_tarea t JOIN med.archivo a "
                    "ON a.id=(t.payload->>'archivo_id')::bigint WHERE t.proceso_id=%s",
                    (process_id,),
                ).fetchone()["total"]
                title, body, link, kind = finished_upload_notice(
                    process["medicion_id"], process_id, process["estado"], rejected,
                )
                conn.execute(
                    "INSERT INTO aud.notificacion(usuario_id,titulo,cuerpo,enlace,tipo,proceso_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (process["creado_por"], title, body, link, kind, process_id),
                )
        except psycopg.Error as exc:
            # El aviso no debe revertir una ingesta ya confirmada. recover() lo reintentará.
            logger.warning("No se pudo registrar el aviso de ingesta %s; SQLSTATE=%s",
                           process_id, exc.sqlstate or "desconocido")

    def claim(self, worker_id: str) -> ClaimedTask | None:
        with self._connect() as conn:
            ingest_policy(conn)
            row = conn.execute(
                "WITH candidate AS (SELECT t.id FROM prc.proceso_tarea t "
                "JOIN prc.proceso p ON p.id=t.proceso_id "
                "WHERE t.cola=%s AND t.tipo=%s AND t.estado='en_cola' AND t.disponible_en<=now() "
                "AND (NOT EXISTS (SELECT 1 FROM prc.proceso prep WHERE prep.medicion_id=p.medicion_id "
                "AND prep.tipo='preparar_medicion') OR EXISTS (SELECT 1 FROM prc.proceso prep "
                "WHERE prep.medicion_id=p.medicion_id AND prep.tipo='preparar_medicion' "
                "AND prep.estado='completado')) "
                "ORDER BY t.prioridad,t.disponible_en,t.id FOR UPDATE OF t SKIP LOCKED LIMIT 1) "
                "UPDATE prc.proceso_tarea t SET estado='en_ejecucion',intentos=intentos+1,"
                "iniciado_en=COALESCE(iniciado_en,now()),latido=now(),worker=%s "
                "FROM candidate WHERE t.id=candidate.id "
                "RETURNING t.id,t.proceso_id,t.intentos,t.payload",
                (QUEUE, TYPE, worker_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE prc.proceso SET estado='en_ejecucion',"
                         "iniciado_en=COALESCE(iniciado_en,now()) WHERE id=%s", (row["proceso_id"],))
            return ClaimedTask(row["id"], row["proceso_id"], row["intentos"], row["payload"])

    def job(self, task: ClaimedTask, worker_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT t.payload,p.id AS proceso_id,p.cuenta_id,p.medicion_id,p.opciones,"
                "a.id AS archivo_id,a.s3_bucket,a.s3_key,a.nombre,a.sha256,a.formato_id,"
                "f.extensiones,f.codificacion,f.delimitador,f.zona_horaria,f.fecha_min "
                "FROM prc.proceso_tarea t JOIN prc.proceso p ON p.id=t.proceso_id "
                "JOIN med.archivo a ON a.id=(t.payload->>'archivo_id')::bigint "
                "JOIN cfg.formato_archivo f ON f.id=a.formato_id "
                "WHERE t.id=%s AND t.worker=%s AND t.estado='en_ejecucion' "
                "AND t.cola=%s AND t.tipo=%s AND p.id=%s AND p.tipo=%s "
                "AND p.cuenta_id=(t.payload->>'cuenta_id')::int "
                "AND p.medicion_id=(t.payload->>'medicion_id')::int "
                "AND a.medicion_id=p.medicion_id AND a.s3_bucket='local' AND a.sha256 IS NOT NULL",
                (task.id, worker_id, QUEUE, TYPE, task.process_id, TYPE),
            ).fetchone()
            if row is None or row["formato_id"] != "talkwalker_simple":
                raise ValueError("Tarea de archivo inválida o formato aún sin mapeo")
            mapping = conn.execute(
                "SELECT campo_destino,columnas_origen,transformacion,requerido "
                "FROM cfg.formato_columna WHERE formato_id=%s ORDER BY campo_destino",
                (row["formato_id"],),
            ).fetchall()
            networks = {item["codigo"]: item["id"] for item in conn.execute(
                "SELECT id,codigo FROM cat.red").fetchall()}
            origin = conn.execute("SELECT id FROM cat.origen WHERE codigo='archivo'").fetchone()
            if not mapping or not networks or origin is None:
                raise ValueError("Faltan catálogos técnicos de ingesta")
            extension = row["nombre"].rsplit(".", 1)[-1].lower()
            if extension not in row["extensiones"]:
                raise ValueError("La extensión del archivo no coincide con el formato")
            return {"key": row["s3_key"], "sha256": row["sha256"], "extension": extension,
                    "encoding": row["codificacion"], "delimiter": row["delimitador"],
                    "timezone": row["zona_horaria"], "fecha_min": row["fecha_min"],
                    "mapping": mapping, "networks": networks,
                    "offset": int(row["payload"].get("offset", 0)),
                    "cuenta_id": row["cuenta_id"], "medicion_id": row["medicion_id"],
                    "archivo_id": row["archivo_id"], "origin_id": origin["id"],
                    "options": row["opciones"].get("al_incorporar") or {}}

    def _owned(self, conn: psycopg.Connection, task: ClaimedTask, worker_id: str) -> dict:
        row = conn.execute(
            "SELECT id,payload FROM prc.proceso_tarea WHERE id=%s AND proceso_id=%s "
            "AND cola=%s AND tipo=%s AND worker=%s AND estado='en_ejecucion' FOR UPDATE",
            (task.id, task.process_id, QUEUE, TYPE, worker_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("Se perdió la propiedad de la tarea")
        return row

    @staticmethod
    def _update_current(conn: psycopg.Connection, job: dict, fingerprint: dict,
                        row: dict, period: int) -> str | None:
        """Actualiza solo datos de origen si la huella aún apunta a la principal."""
        if fingerprint["ubicacion"] != "p":
            return "Registro histórico: huella fuera de la base principal"
        if fingerprint["periodo"] != period:
            return "Fecha nueva en otro período: requiere revisión sin mover el registro"
        archived = conn.execute(
            "SELECT estado FROM ops.archivado WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s",
            (job["cuenta_id"], job["medicion_id"], period),
        ).fetchone()
        if archived is not None and archived["estado"] != "rehidratado":
            return "Período en proceso de archivado o archivado; no se actualizó"
        existing = conn.execute(
            "SELECT editado FROM dat.registro WHERE cuenta_id=%s AND medicion_id=%s "
            "AND periodo=%s AND registro_id=%s FOR UPDATE",
            (job["cuenta_id"], job["medicion_id"], period, fingerprint["registro_id"]),
        ).fetchone()
        if existing is None:
            return "Huella sin registro principal verificable; no se actualizó"
        # No cambia fecha, período, identidad, ejecución, decisiones del analista
        # ni dat.registro_estado (incluidas las métricas calculadas por Syntra).
        updated = conn.execute(
            "UPDATE dat.registro SET red_id=%s,"
            "titulo=CASE WHEN editado THEN titulo ELSE COALESCE(%s,titulo) END,"
            "texto=CASE WHEN editado THEN texto ELSE COALESCE(%s,texto) END,"
            "fecha_indexado=COALESCE(%s,fecha_indexado),"
            "idioma=COALESCE(%s,idioma),tipo_contenido=COALESCE(%s,tipo_contenido),"
            "url_padre=COALESCE(%s,url_padre),autor_id_ext=COALESCE(%s,autor_id_ext),"
            "autor_usuario=COALESCE(%s,autor_usuario),autor_nombre=COALESCE(%s,autor_nombre),"
            "autor_seguidores=COALESCE(%s,autor_seguidores),pais=COALESCE(%s,pais),"
            "region=COALESCE(%s,region),ciudad=COALESCE(%s,ciudad),"
            "media_urls=COALESCE(%s,media_urls),extra=COALESCE(%s,extra),"
            "sentimiento_fuente=COALESCE(%s,sentimiento_fuente) "
            "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s "
            "AND EXISTS (SELECT 1 FROM dat.registro_huella h WHERE h.cuenta_id=%s "
            "AND h.medicion_id=%s AND h.url_hash=%s AND h.registro_id=%s "
            "AND h.periodo=%s AND h.ubicacion='p') "
            "AND NOT EXISTS (SELECT 1 FROM ops.archivado a WHERE a.cuenta_id=%s "
            "AND a.medicion_id=%s AND a.periodo=%s AND a.estado<>'rehidratado')",
            (row["red_id"], row.get("titulo"), row.get("texto"), row.get("fecha_indexado"),
             row.get("idioma"), row.get("tipo_contenido"), row.get("url_padre"),
             row.get("autor_id_ext"), row.get("autor_usuario"), row.get("autor_nombre"),
             row.get("autor_seguidores"), row.get("pais"), row.get("region"), row.get("ciudad"),
             row.get("media_urls"), Jsonb(row["extra"]) if row.get("extra") else None,
             row.get("sentimiento_fuente"), job["cuenta_id"], job["medicion_id"], period,
             fingerprint["registro_id"], job["cuenta_id"], job["medicion_id"],
             fingerprint["url_hash"], fingerprint["registro_id"], period,
             job["cuenta_id"], job["medicion_id"], period),
        )
        return None if updated.rowcount == 1 else "El registro cambió durante la comprobación; no se actualizó"

    def _classify_chunk(self, conn: psycopg.Connection, valid: list[dict], job: dict
                        ) -> tuple[list[tuple[dict, int, int]], int, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for row in valid:
            groups.setdefault(row["url_canonica"], []).append(row)
        if not groups:
            return [], 0, []
        # El mismo orden global de locks evita interbloqueos entre cargas
        # concurrentes; el PK de huellas mantiene el aislamiento por ámbito.
        locks = [f"{job['cuenta_id']}:{job['medicion_id']}:{key}" for key in sorted(groups)]
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(v,0)) "
            "FROM (SELECT unnest(%s::text[]) AS v ORDER BY v) s", (locks,),
        ).fetchall()
        candidate_to_key: dict[bytes, str] = {}
        for key, rows in groups.items():
            for fingerprint in (rows[0]["url_hash"], *rows[0]["huellas_heredadas"]):
                candidate_to_key[fingerprint] = key
        found: dict[str, list[dict]] = {key: [] for key in groups}
        for fingerprint in conn.execute(
            "SELECT url_hash,registro_id,periodo,ubicacion FROM dat.registro_huella "
            "WHERE cuenta_id=%s AND medicion_id=%s AND url_hash=ANY(%s::bytea[])",
            (job["cuenta_id"], job["medicion_id"], list(candidate_to_key)),
        ).fetchall():
            found[candidate_to_key[fingerprint["url_hash"]]].append(fingerprint)
        accepted: list[tuple[dict, int, int]] = []
        new_groups: list[tuple[dict, int, int]] = []
        duplicates = 0
        protected: list[dict] = []
        for key, rows in groups.items():
            row = rows[0]  # La primera fila válida del bloque prevalece.
            matches = found[key]
            period = int(row["fecha_publicacion"].astimezone(
                ZoneInfo("America/Bogota")).strftime("%Y%m"))
            if len(matches) > 1:
                reason = "Varias huellas heredadas coinciden con la URL; requiere revisión"
                protected.extend({"row": item["_fila"], "reason": reason, "duplicate": False,
                                  "data": {"url": item["url"]}} for item in rows)
                continue
            if matches:
                duplicates += len(rows)
                reason = self._update_current(conn, job, matches[0], row, period)
                if reason:
                    protected.append({"row": row["_fila"], "reason": reason, "duplicate": True,
                                      "data": {"url": row["url"]}})
                continue
            new_groups.append((row, period, len(rows)))
            duplicates += len(rows) - 1
        if new_groups:
            identifiers = [item["id"] for item in conn.execute(
                "SELECT nextval('dat.registro_id_seq') AS id FROM generate_series(1,%s)",
                (len(new_groups),),
            )]
            cursor = conn.cursor()
            cursor.executemany(
                "INSERT INTO dat.registro_huella(cuenta_id,medicion_id,url_hash,registro_id,periodo) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING registro_id",
                [(job["cuenta_id"], job["medicion_id"], row["url_hash"], identifier, period)
                 for (row, period, _), identifier in zip(new_groups, identifiers)],
                returning=True,
            )
            for (row, period, _), identifier in zip(new_groups, identifiers):
                if cursor.fetchone() is None:
                    raise RuntimeError("Conflicto concurrente de huella; se reintentará el bloque")
                accepted.append((row, identifier, period))
                cursor.nextset()
            cursor.close()
        return accepted, duplicates, protected

    def save_chunk(self, task: ClaimedTask, worker_id: str, valid: list[dict],
                   rejected: list[dict], offset: int, job: dict) -> None:
        with self._connect() as conn:
            timeout = ingest_policy(conn)["timeout_ms"]
            conn.execute("SELECT set_config('statement_timeout',%s,true)", (str(timeout),))
            owned = self._owned(conn, task, worker_id)
            if offset < int(owned["payload"].get("offset", 0)):
                raise RuntimeError("El checkpoint retrocedió")
            periods = sorted({int(row["fecha_publicacion"].astimezone(ZoneInfo("America/Bogota")).strftime("%Y%m"))
                              for row in valid} | {int(datetime.now(ZoneInfo("America/Bogota")).strftime("%Y%m"))})
            conn.execute("SELECT ops.fn_asegurar_periodos_ingesta(%s,%s,%s)",
                         (task.id, worker_id, periods))
            execution = conn.execute("SELECT id FROM dat.ejecucion WHERE tarea_id=%s ORDER BY id LIMIT 1",
                                     (task.id,)).fetchone()
            if execution is None:
                execution = conn.execute(
                    "INSERT INTO dat.ejecucion(cuenta_id,medicion_id,proceso_id,tarea_id,origen_id,archivo_id,post) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (job["cuenta_id"], job["medicion_id"], task.process_id, task.id,
                     job["origin_id"], job["archivo_id"], Jsonb(job["options"])),
                ).fetchone()
            accepted, duplicates, protected = self._classify_chunk(conn, valid, job)
            new = len(accepted)
            input_rejected = len(rejected)
            rejected_count = input_rejected + sum(not item["duplicate"] for item in protected)
            if accepted:
                records = [
                    (job["cuenta_id"], job["medicion_id"], period, identifier, execution["id"],
                     job["origin_id"], row["red_id"], row["url"], row["url_hash"], row["fecha_publicacion"],
                     row.get("fecha_indexado"), row.get("titulo"), row.get("texto"), row.get("idioma"),
                     row.get("tipo_contenido"), row.get("url_padre"), row.get("autor_id_ext"),
                     row.get("autor_usuario"), row.get("autor_nombre"), row.get("autor_seguidores"),
                     row.get("pais"), row.get("region"), row.get("ciudad"), row.get("es_rt") or False,
                     row.get("es_comentario") or False, row.get("media_urls"), Jsonb(row.get("extra") or {}),
                     row.get("sentimiento_fuente"))
                    for row, identifier, period in accepted
                ]
                conn.cursor().executemany(
                    "INSERT INTO dat.registro(cuenta_id,medicion_id,periodo,registro_id,ejecucion_id,"
                    "origen_id,red_id,url,url_hash,fecha_publicacion,fecha_indexado,titulo,texto,idioma,"
                    "tipo_contenido,url_padre,autor_id_ext,autor_usuario,autor_nombre,autor_seguidores,"
                    "pais,region,ciudad,es_rt,es_comentario,media_urls,extra,sentimiento_fuente) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    records,
                )
                options = job["options"]
                incorporated, relevance_state = initial_ingest_state(options)
                states = [
                    (job["cuenta_id"], job["medicion_id"], period, identifier,
                     incorporated, incorporated,
                     relevance_state, 0 if options.get("sentimiento") else 4,
                     0 if options.get("clusters") else 4, 0 if options.get("bots") else 4,
                     row.get("likes"), row.get("comentarios"), row.get("compartidos"),
                     row.get("reproducciones"), row.get("alcance"), task.process_id)
                    for row, identifier, period in accepted
                ]
                conn.cursor().executemany(
                    "INSERT INTO dat.registro_estado(cuenta_id,medicion_id,periodo,registro_id,"
                    "incorporado,incorporado_en,st_relevancia,st_sentimiento,st_cluster,st_bots,"
                    "likes,comentarios,compartidos,reproducciones,alcance,ultimo_proceso_id) "
                    "VALUES (%s,%s,%s,%s,%s,CASE WHEN %s THEN now() ELSE NULL END,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    states,
                )
            rejected_period = int(datetime.now(ZoneInfo("America/Bogota")).strftime("%Y%m"))
            for item in (*rejected, *protected):
                conn.execute(
                    "INSERT INTO dat.registro_evento(cuenta_id,medicion_id,periodo,paso,proceso_id,tarea_id,"
                    "intento,estado,codigo_error,mensaje,detalle) VALUES (%s,%s,%s,1,%s,%s,%s,3,%s,%s,%s)",
                    (job["cuenta_id"], job["medicion_id"], rejected_period, task.process_id,
                     task.id, task.attempts, "fila_rechazada", item["reason"],
                     Jsonb({"fila": item["row"], "original": item["data"]})),
                )
            conn.execute(
                "UPDATE dat.ejecucion SET n_leidos=n_leidos+%s,n_nuevos=n_nuevos+%s,"
                "n_duplicados=n_duplicados+%s,n_rechazados=n_rechazados+%s WHERE id=%s",
                (len(valid)+input_rejected, new, duplicates, rejected_count, execution["id"]),
            )
            conn.execute("UPDATE med.archivo SET estado='procesando',filas_leidas=COALESCE(filas_leidas,0)+%s,"
                         "filas_validas=COALESCE(filas_validas,0)+%s,"
                         "filas_rechazadas=COALESCE(filas_rechazadas,0)+%s WHERE id=%s",
                         (len(valid)+input_rejected, len(valid)-rejected_count+input_rejected,
                          rejected_count, job["archivo_id"]))
            conn.execute("UPDATE prc.proceso_tarea SET payload=jsonb_set(payload,'{offset}',to_jsonb(%s::integer),true),"
                         "ok=ok+%s,errores=errores+%s,latido=now() WHERE id=%s",
                         (offset, new, rejected_count, task.id))

    def finish(self, task: ClaimedTask, worker_id: str) -> None:
        with self._connect() as conn:
            row = self._owned(conn, task, worker_id)
            file_id = row["payload"]["archivo_id"]
            conn.execute("UPDATE med.archivo SET estado='procesado',error=NULL WHERE id=%s", (file_id,))
            conn.execute("UPDATE prc.proceso_tarea SET estado='completado',finalizado_en=now(),"
                         "latido=NULL,worker=NULL,error_codigo=NULL,error_mensaje=NULL WHERE id=%s", (task.id,))
            self._aggregate(conn, task.process_id)
        self._notify_terminal(task.process_id)

    def fail(self, task: ClaimedTask, worker_id: str, code: str) -> None:
        with self._connect() as conn:
            policy = ingest_policy(conn)
            row = conn.execute("SELECT id,payload FROM prc.proceso_tarea WHERE id=%s AND worker=%s "
                               "AND estado='en_ejecucion' FOR UPDATE", (task.id, worker_id)).fetchone()
            if row is None:
                return
            delay = ingest_retry_delay(task.attempts, policy)
            terminal = delay is None
            safe_code = code if code in {"ingesta_fallida", "archivo_invalido", "tiempo_agotado"} else "ingesta_fallida"
            conn.execute("UPDATE prc.proceso_tarea SET estado=%s,worker=NULL,latido=NULL,"
                         "disponible_en=now()+(%s*interval '1 millisecond'),"
                         "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,"
                         "error_codigo=%s,error_mensaje='La ingesta falló; consultar el diagnóstico técnico' "
                         "WHERE id=%s", ("error" if terminal else "en_cola", delay or 0, terminal, safe_code, task.id))
            if terminal:
                conn.execute("UPDATE med.archivo SET estado='error',error=%s WHERE id=%s",
                             (safe_code, row["payload"].get("archivo_id")))
                self._aggregate(conn, task.process_id)
            else:
                conn.execute("UPDATE prc.proceso SET estado='en_cola',detalle=%s WHERE id=%s",
                             (safe_code, task.process_id))
        if terminal:
            self._notify_terminal(task.process_id)

    def _pulse(self, task: ClaimedTask, worker_id: str, stop: Event) -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                with self._connect() as conn:
                    conn.execute("UPDATE prc.proceso_tarea SET latido=now() WHERE id=%s AND worker=%s "
                                 "AND estado='en_ejecucion'", (task.id, worker_id))
            except psycopg.Error as exc:
                logger.warning("No se renovó el lease de ingesta %s; SQLSTATE=%s",
                               task.id, exc.sqlstate or "desconocido")

    def process(self, task: ClaimedTask, worker_id: str) -> None:
        stop = Event()
        pulse = Thread(target=self._pulse, args=(task, worker_id, stop), daemon=True)
        pulse.start()
        try:
            with self._connect() as conn:
                timeout = ingest_policy(conn)["timeout_ms"]
            IngestFile(self, self.source).execute(task, worker_id, timeout)
        except Exception as exc:
            code = "tiempo_agotado" if isinstance(exc, TimeoutError) else "archivo_invalido" if isinstance(exc, ValueError) else "ingesta_fallida"
            try:
                self.fail(task, worker_id, code)
            except Exception as failure:
                logger.error("No se pudo registrar el fallo de ingesta %s; SQLSTATE=%s",
                             task.id, getattr(failure, "sqlstate", None) or "desconocido")
                return
            detail = (exc.diag.message_primary if isinstance(exc, psycopg.errors.InsufficientPrivilege)
                      else None)
            logger.warning("Falló ingesta %s; código=%s clase=%s SQLSTATE=%s permiso=%s",
                           task.id, code, type(exc).__name__, getattr(exc, "sqlstate", None) or "no_sql",
                           detail or "no_aplica")
        finally:
            stop.set()
            pulse.join(timeout=2)
