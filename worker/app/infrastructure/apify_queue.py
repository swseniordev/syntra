"""Cola durable q.apify: lanza actores de Apify y persiste sus resultados.

Cada tarea (``prc.proceso_tarea`` con ``cola='q.apify'`` y ``tipo='apify'``)
corresponde a UNA red del proceso de scraping (``clave='red:<codigo>'``). El
consumidor lanza el actor con ``start()``, sondea su estado renovando el latido,
y al terminar normaliza el dataset a ``dat.registro`` reutilizando la misma
deduplicación por huella que la ingesta de archivos.

El ``run_id`` de Apify se guarda en ``proceso_tarea.ref_externa``: si el worker
pierde el lease a mitad de un sondeo, al reclamar de nuevo la tarea se reanuda el
mismo run en vez de lanzar otro.
"""

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

from app.application.plan_compute import PlanCompute
from app.application.ports import ScrapeProvider
from app.config import WorkerSettings
from app.domain.apify import build_run_input, is_terminal, map_item, succeeded
from app.domain.ingest_actions import initial_ingest_state
from app.infrastructure.fanout import PostgresFanout, chunk_size
from app.domain.tasks import ClaimedTask
from app.domain.talkwalker import RejectedRow


QUEUE = "q.apify"
TASK_TYPE = "apify"
PROC_TYPE = "carga_scraper"
OPERACION = "carga_scraper"
HEARTBEAT_SECONDS = 15
POLL_RUN_SECONDS = 10
logger = logging.getLogger("syntra.worker.apify")

_BOGOTA = ZoneInfo("America/Bogota")


def _period(moment: datetime) -> int:
    return int(moment.astimezone(_BOGOTA).strftime("%Y%m"))


def scrape_policy(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        "SELECT max_intentos,backoff_base_ms,backoff_max_ms,timeout_ms "
        "FROM ops.politica_reintento WHERE operacion=%s", (OPERACION,),
    ).fetchone()
    if (row is None or not 1 <= row["max_intentos"] <= 10 or row["backoff_base_ms"] < 1
            or row["backoff_max_ms"] < row["backoff_base_ms"] or row["timeout_ms"] < 1):
        raise ValueError("La política persistida de scraping falta o es inválida")
    return row


def scrape_retry_delay(attempt: int, policy: dict) -> int | None:
    if attempt >= policy["max_intentos"]:
        return None
    return policy["backoff_base_ms"] if attempt == 1 else policy["backoff_max_ms"]


class ApifyQueue:
    def __init__(self, settings: WorkerSettings,
                 connect: Callable[[], psycopg.Connection] | None = None,
                 provider: ScrapeProvider | None = None):
        self.settings = settings
        self._connect = connect or self._database_connection
        self._provider = provider
        self._own_provider = provider is None
        self._next_compute_scan = 0.0

    def _database_connection(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.database_host, port=self.settings.database_port,
            dbname=self.settings.database_name, user=self.settings.database_user,
            passfile=str(self.settings.database_passfile), row_factory=dict_row,
            connect_timeout=5, application_name="syntra_scraper_worker",
        )

    def provider(self) -> ScrapeProvider:
        if self._provider is None:
            from app.infrastructure.apify_client import ApifyScrapeProvider
            self._provider = ApifyScrapeProvider(self.settings.apify_token_file)
        return self._provider

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
            policy = scrape_policy(conn)
            tasks = conn.execute(
                "SELECT id,proceso_id,intentos,ref_externa FROM prc.proceso_tarea "
                "WHERE cola=%s AND tipo=%s AND estado='en_ejecucion' "
                "AND (latido IS NULL OR latido<now()-(%s*interval '1 second')) "
                "ORDER BY id FOR UPDATE SKIP LOCKED",
                (QUEUE, TASK_TYPE, self.settings.lease_seconds),
            ).fetchall()
            for task in tasks:
                delay = scrape_retry_delay(task["intentos"], policy)
                terminal = delay is None
                # ref_externa se conserva: al reclamar se reanuda el mismo run de Apify.
                conn.execute(
                    "UPDATE prc.proceso_tarea SET estado=%s,worker=NULL,latido=NULL,"
                    "disponible_en=now()+(%s*interval '1 millisecond'),"
                    "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,"
                    "error_codigo='worker_interrumpido',"
                    "error_mensaje='Worker de scraping interrumpido' WHERE id=%s",
                    ("error" if terminal else "en_cola", delay or 0, terminal, task["id"]),
                )
                if terminal:
                    self._aggregate(conn, task["proceso_id"])
                else:
                    conn.execute("UPDATE prc.proceso SET estado='en_cola' WHERE id=%s",
                                 (task["proceso_id"],))
            recovered = len(tasks)
        if time.monotonic() >= self._next_compute_scan:
            self._next_compute_scan = time.monotonic() + 60
            self._sweep_compute()
        return recovered

    def _sweep_compute(self) -> None:
        """Reparte cómputos de scrapings completados cuyo fan-out no quedó registrado."""
        try:
            with self._connect() as conn:
                pending = conn.execute(
                    "SELECT p.id FROM prc.proceso p WHERE p.tipo='carga_scraper' "
                    "AND p.estado='completado' AND p.finalizado_en>=now()-interval '1 day' "
                    "AND NOT EXISTS (SELECT 1 FROM prc.proceso c WHERE c.idempotencia='computo:'||p.id) "
                    "ORDER BY p.id DESC LIMIT 100",
                ).fetchall()
            for row in pending:
                self._plan_compute(row["id"])
        except psycopg.Error as exc:
            logger.warning("No se pudo barrer cómputos de scraping; SQLSTATE=%s",
                           exc.sqlstate or "desconocido")

    def claim(self, worker_id: str) -> ClaimedTask | None:
        with self._connect() as conn:
            scrape_policy(conn)
            row = conn.execute(
                "WITH candidate AS (SELECT t.id FROM prc.proceso_tarea t "
                "JOIN prc.proceso p ON p.id=t.proceso_id "
                "WHERE t.cola=%s AND t.tipo=%s AND t.estado='en_cola' AND t.disponible_en<=now() "
                "ORDER BY t.prioridad,t.disponible_en,t.id FOR UPDATE OF t SKIP LOCKED LIMIT 1) "
                "UPDATE prc.proceso_tarea t SET estado='en_ejecucion',intentos=intentos+1,"
                "iniciado_en=COALESCE(iniciado_en,now()),latido=now(),worker=%s "
                "FROM candidate WHERE t.id=candidate.id "
                "RETURNING t.id,t.proceso_id,t.intentos,t.ref_externa",
                (QUEUE, TASK_TYPE, worker_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE prc.proceso SET estado='en_ejecucion',"
                         "iniciado_en=COALESCE(iniciado_en,now()) WHERE id=%s", (row["proceso_id"],))
            return ClaimedTask(row["id"], row["proceso_id"], row["intentos"], {"ref_externa": row["ref_externa"]})

    def job(self, task: ClaimedTask, worker_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT t.clave,t.ref_externa,p.cuenta_id,p.medicion_id,p.scraper_id,"
                "s.transcribir,s.post_incorporar,s.post_relevancia,s.post_sentimiento,"
                "s.post_clusters,s.post_bots "
                "FROM prc.proceso_tarea t JOIN prc.proceso p ON p.id=t.proceso_id "
                "JOIN med.scraper s ON s.id=p.scraper_id "
                "WHERE t.id=%s AND t.worker=%s AND t.estado='en_ejecucion' "
                "AND t.cola=%s AND t.tipo=%s AND p.id=%s AND p.tipo=%s",
                (task.id, worker_id, QUEUE, TASK_TYPE, task.process_id, PROC_TYPE),
            ).fetchone()
            if row is None or not str(row["clave"] or "").startswith("red:"):
                raise ValueError("Tarea de scraping inválida o sin red en la clave")
            red_code = row["clave"].split(":", 1)[1].strip().lower()
            red = conn.execute("SELECT id FROM cat.red WHERE codigo=%s", (red_code,)).fetchone()
            # El catálogo oficial usa 'scrapper' (doble p, typo histórico asumido por el front).
            origin = conn.execute("SELECT id FROM cat.origen WHERE codigo='scrapper'").fetchone()
            link = conn.execute(
                "SELECT registros,actor_id FROM med.scraper_red "
                "WHERE scraper_id=%s AND red_id=%s AND activo",
                (row["scraper_id"], red["id"] if red else None),
            ).fetchone()
            if red is None or origin is None or link is None:
                raise ValueError("Faltan catálogos o la red no está activa en el scraper")
            if link["actor_id"] is not None:
                actor = conn.execute(
                    "SELECT actor,max_registros,memoria_mb FROM cfg.actor_scraping "
                    "WHERE id=%s AND red_id=%s AND estado_id=1 AND uso='busqueda'",
                    (link["actor_id"], red["id"]),
                ).fetchone()
            else:
                actor = conn.execute(
                    "SELECT actor,max_registros,memoria_mb FROM cfg.actor_scraping "
                    "WHERE red_id=%s AND estado_id=1 AND uso='busqueda' ORDER BY id LIMIT 1",
                    (red["id"],),
                ).fetchone()
            if actor is None:
                raise ValueError("No hay actor de Apify activo para la red")
            keywords = [item["palabra"] for item in conn.execute(
                "SELECT palabra FROM med.scraper_palabra WHERE scraper_id=%s AND fuente=%s",
                (row["scraper_id"], red_code),
            ).fetchall()]
            target = min(int(link["registros"]), int(actor["max_registros"]))
            run_input = build_run_input(actor["actor"], keywords, target, bool(row["transcribir"]))
            options = {"incorporar": row["post_incorporar"], "relevancia": row["post_relevancia"],
                       "sentimiento": row["post_sentimiento"], "clusters": row["post_clusters"],
                       "bots": row["post_bots"]}
            return {"cuenta_id": row["cuenta_id"], "medicion_id": row["medicion_id"],
                    "scraper_id": row["scraper_id"], "origin_id": origin["id"],
                    "red_id": red["id"], "red_code": red_code, "actor": actor["actor"],
                    # Cuota: la memoria por corrida no supera el presupuesto del plan Apify.
                    "memory_mb": min(int(actor["memoria_mb"]), self.settings.apify_max_memory_mb),
                    "run_input": run_input,
                    "target": target, "options": options, "ref_externa": row["ref_externa"],
                    "clave": row["clave"]}

    def _ensure_run(self, task: ClaimedTask, worker_id: str, job: dict) -> str:
        if job["ref_externa"]:
            return job["ref_externa"]
        run_id = self.provider().start_run(job["actor"], job["run_input"], job["memory_mb"])
        with self._connect() as conn:
            conn.execute(
                "UPDATE prc.proceso_tarea SET ref_externa=%s,objetivo=%s,latido=now() "
                "WHERE id=%s AND worker=%s AND estado='en_ejecucion'",
                (run_id, job["target"], task.id, worker_id),
            )
        return run_id

    def _poll(self, task: ClaimedTask, worker_id: str, run_id: str, timeout_ms: int,
              stop: Event) -> dict:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            status = self.provider().run_status(run_id)
            self._touch(task, worker_id)
            if is_terminal(status.get("status")):
                return status
            if stop.is_set():
                raise RuntimeError("Worker detenido durante el sondeo del run")
            if time.monotonic() >= deadline:
                raise TimeoutError("El run de Apify excedió el tiempo máximo")
            stop.wait(POLL_RUN_SECONDS)

    def _touch(self, task: ClaimedTask, worker_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE prc.proceso_tarea SET latido=now() WHERE id=%s AND worker=%s "
                         "AND estado='en_ejecucion'", (task.id, worker_id))

    def persist(self, task: ClaimedTask, worker_id: str, job: dict, items: list[dict]) -> None:
        with self._connect() as conn:
            owned = conn.execute(
                "SELECT id FROM prc.proceso_tarea WHERE id=%s AND proceso_id=%s AND cola=%s "
                "AND tipo=%s AND worker=%s AND estado='en_ejecucion' FOR UPDATE",
                (task.id, task.process_id, QUEUE, TASK_TYPE, worker_id),
            ).fetchone()
            if owned is None:
                raise RuntimeError("Se perdió la propiedad de la tarea de scraping")
            valid: list[dict] = []
            rejected: list[dict] = []
            for item in items:
                try:
                    valid.append(map_item(job["red_code"], job["red_id"], item))
                except RejectedRow as exc:
                    rejected.append({"reason": str(exc), "data": item})
            periods = sorted({_period(row["fecha_publicacion"]) for row in valid}
                             | {_period(datetime.now(_BOGOTA))})
            # Wrapper SECURITY DEFINER análogo al de ingesta: valida la tarea q.apify
            # y crea las particiones como rol privilegiado (el worker no tiene DDL en dat).
            conn.execute("SELECT ops.fn_asegurar_periodos_scraper(%s,%s,%s)",
                         (task.id, worker_id, periods))
            execution = conn.execute(
                "INSERT INTO dat.ejecucion(cuenta_id,medicion_id,proceso_id,tarea_id,origen_id,"
                "red_id,scraper_id,detalle,post) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (job["cuenta_id"], job["medicion_id"], task.process_id, task.id, job["origin_id"],
                 job["red_id"], job["scraper_id"], job["clave"], Jsonb(job["options"])),
            ).fetchone()
            incorporated, relevance_state = initial_ingest_state(job["options"])
            options = job["options"]
            new = duplicates = 0
            for row in valid:
                period = _period(row["fecha_publicacion"])
                identifier = conn.execute(
                    "INSERT INTO dat.registro_huella(cuenta_id,medicion_id,url_hash,registro_id,periodo) "
                    "VALUES (%s,%s,%s,nextval('dat.registro_id_seq'),%s) "
                    "ON CONFLICT DO NOTHING RETURNING registro_id",
                    (job["cuenta_id"], job["medicion_id"], row["url_hash"], period),
                ).fetchone()
                if identifier is None:
                    duplicates += 1
                    continue
                registro_id = identifier["registro_id"]
                conn.execute(
                    "INSERT INTO dat.registro(cuenta_id,medicion_id,periodo,registro_id,ejecucion_id,"
                    "origen_id,red_id,scraper_id,url,url_hash,fecha_publicacion,fecha_indexado,titulo,"
                    "texto,idioma,tipo_contenido,url_padre,autor_id_ext,autor_usuario,autor_nombre,"
                    "autor_seguidores,pais,region,ciudad,es_rt,es_comentario,media_urls,extra,"
                    "sentimiento_fuente) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (job["cuenta_id"], job["medicion_id"], period, registro_id, execution["id"],
                     job["origin_id"], row["red_id"], job["scraper_id"], row["url"], row["url_hash"],
                     row["fecha_publicacion"], row["fecha_indexado"], row["titulo"], row["texto"],
                     row["idioma"], row["tipo_contenido"], row["url_padre"], row["autor_id_ext"],
                     row["autor_usuario"], row["autor_nombre"], row["autor_seguidores"], row["pais"],
                     row["region"], row["ciudad"], row["es_rt"], row["es_comentario"],
                     row["media_urls"], Jsonb(row["extra"]), row["sentimiento_fuente"]),
                )
                conn.execute(
                    "INSERT INTO dat.registro_estado(cuenta_id,medicion_id,periodo,registro_id,"
                    "incorporado,incorporado_en,st_relevancia,st_sentimiento,st_cluster,st_bots,"
                    "st_embedding,likes,comentarios,compartidos,reproducciones,alcance,ultimo_proceso_id) "
                    "VALUES (%s,%s,%s,%s,%s,CASE WHEN %s THEN now() ELSE NULL END,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (job["cuenta_id"], job["medicion_id"], period, registro_id, incorporated,
                     incorporated, relevance_state, 0 if options.get("sentimiento") else 4,
                     0 if options.get("clusters") else 4, 0 if options.get("bots") else 4,
                     # El embedding solo se necesita para clustering.
                     0 if options.get("clusters") else 4,
                     row["likes"], row["comentarios"], row["compartidos"], row["reproducciones"],
                     row["alcance"], task.process_id),
                )
                new += 1
            rejected_period = _period(datetime.now(_BOGOTA))
            for item in rejected:
                conn.execute(
                    "INSERT INTO dat.registro_evento(cuenta_id,medicion_id,periodo,paso,proceso_id,"
                    "tarea_id,intento,estado,codigo_error,mensaje,detalle) "
                    "VALUES (%s,%s,%s,1,%s,%s,%s,3,%s,%s,%s)",
                    (job["cuenta_id"], job["medicion_id"], rejected_period, task.process_id,
                     task.id, task.attempts, "item_rechazado", item["reason"], Jsonb(item["data"])),
                )
            conn.execute(
                "UPDATE dat.ejecucion SET n_leidos=%s,n_nuevos=%s,n_duplicados=%s,n_rechazados=%s "
                "WHERE id=%s", (len(items), new, duplicates, len(rejected), execution["id"]),
            )
            conn.execute("UPDATE prc.proceso_tarea SET ok=%s,errores=%s,latido=now() WHERE id=%s",
                         (new, len(rejected), task.id))

    def finish(self, task: ClaimedTask, worker_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE prc.proceso_tarea SET estado='completado',finalizado_en=now(),"
                         "latido=NULL,worker=NULL,error_codigo=NULL,error_mensaje=NULL "
                         "WHERE id=%s AND worker=%s AND estado='en_ejecucion'", (task.id, worker_id))
            self._aggregate(conn, task.process_id)
        # Cuando la última red del scraping cierra el proceso, el scraping converge
        # al mismo cómputo que los archivos (relevancia/sentimiento/embedding → clusters).
        self._plan_compute(task.process_id)

    def _plan_compute(self, process_id: int) -> None:
        """Reparte a q.llm los registros del scraping ya incorporados. Fuera de la
        transacción de cierre e idempotente: un fallo aquí no revierte el scraping."""
        try:
            with self._connect() as conn:
                size = chunk_size(conn)
            planned = PlanCompute(PostgresFanout(self._connect), size).execute(process_id)
            if planned:
                logger.info("Reparto q.llm del scraping %s: %s tareas", process_id, planned)
        except psycopg.Error as exc:
            logger.warning("No se repartió el cómputo del scraping %s; SQLSTATE=%s",
                           process_id, exc.sqlstate or "desconocido")

    def fail(self, task: ClaimedTask, worker_id: str, code: str) -> None:
        with self._connect() as conn:
            policy = scrape_policy(conn)
            row = conn.execute("SELECT id FROM prc.proceso_tarea WHERE id=%s AND worker=%s "
                               "AND estado='en_ejecucion' FOR UPDATE", (task.id, worker_id)).fetchone()
            if row is None:
                return
            delay = scrape_retry_delay(task.attempts, policy)
            terminal = delay is None
            safe_code = code if code in {"scraper_fallido", "scraper_invalido", "tiempo_agotado"} else "scraper_fallido"
            conn.execute("UPDATE prc.proceso_tarea SET estado=%s,worker=NULL,latido=NULL,"
                         "disponible_en=now()+(%s*interval '1 millisecond'),"
                         "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,"
                         "error_codigo=%s,error_mensaje='El scraping falló; consultar el diagnóstico técnico' "
                         "WHERE id=%s", ("error" if terminal else "en_cola", delay or 0, terminal, safe_code, task.id))
            if terminal:
                self._aggregate(conn, task.process_id)
            else:
                conn.execute("UPDATE prc.proceso SET estado='en_cola',detalle=%s WHERE id=%s",
                             (safe_code, task.process_id))

    def _pulse(self, task: ClaimedTask, worker_id: str, stop: Event) -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                self._touch(task, worker_id)
            except psycopg.Error as exc:
                logger.warning("No se renovó el lease de scraping %s; SQLSTATE=%s",
                               task.id, exc.sqlstate or "desconocido")

    def process(self, task: ClaimedTask, worker_id: str) -> None:
        stop = Event()
        pulse = Thread(target=self._pulse, args=(task, worker_id, stop), daemon=True)
        pulse.start()
        try:
            with self._connect() as conn:
                timeout = scrape_policy(conn)["timeout_ms"]
            job = self.job(task, worker_id)
            run_id = self._ensure_run(task, worker_id, job)
            status = self._poll(task, worker_id, run_id, timeout, stop)
            if not succeeded(status.get("status")):
                self.fail(task, worker_id, "scraper_fallido")
                return
            dataset_id = status.get("defaultDatasetId")
            items = self.provider().dataset_items(dataset_id) if dataset_id else []
            self.persist(task, worker_id, job, items)
            self.finish(task, worker_id)
        except Exception as exc:
            code = ("tiempo_agotado" if isinstance(exc, TimeoutError)
                    else "scraper_invalido" if isinstance(exc, ValueError) else "scraper_fallido")
            try:
                self.fail(task, worker_id, code)
            except Exception as failure:
                logger.error("No se pudo registrar el fallo de scraping %s; SQLSTATE=%s",
                             task.id, getattr(failure, "sqlstate", None) or "desconocido")
                return
            detail = exc.diag.message_primary if isinstance(exc, psycopg.errors.InsufficientPrivilege) else None
            logger.warning("Falló scraping %s; código=%s clase=%s SQLSTATE=%s detalle=%s",
                           task.id, code, type(exc).__name__, getattr(exc, "sqlstate", None) or "no_sql",
                           detail or "no_aplica")
        finally:
            stop.set()
            pulse.join(timeout=2)
