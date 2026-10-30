"""Cola durable q.llm: cómputo por registro de relevancia/sentimiento/embedding.

Reclama lotes de ``prc.proceso_tarea`` (cola ``q.llm``) y delega el cómputo en
``ComputeRecords``. Reutiliza el mismo esqueleto probado de ``q.ingesta``
(política de reintentos, lease con latido, recuperación de workers caídos y
agregación del proceso). El orquestador que *encola* estas tareas es una pieza
aparte (incorporación / q.datos) todavía no construida; el contrato de payload
es ``{"registro_ids": [bigint, ...], "periodo": <int>}``.

Prerrequisito operativo (paquete de init, no inferible aquí): el login
``syntra_llm_worker_login`` sobre el rol ``svc_llm`` con su pgpass y los GRANT
correspondientes. Sin eso la cola no puede conectarse.
"""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Callable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.application.compute_records import ComputeRecords
from app.config import WorkerSettings
from app.domain.compute import EMBEDDING, ERROR, OK, RELEVANCIA, SENTIMIENTO
from app.domain.tasks import ClaimedTask, retry_delay_ms
from app.infrastructure.llm_provider import StubLLMProvider

QUEUE = "q.llm"
TYPE = "sentimiento"  # tipo_proceso de referencia; el claim acepta todo cómputo de q.llm
OPERACION = "llm.clasificar"  # ops.politica_reintento
HEARTBEAT_SECONDS = 15
logger = logging.getLogger("syntra.worker.llm")

# Códigos de paso de dat.registro_ia / dat.registro_evento. Reconciliar con el
# catálogo oficial del paquete de init si difiere de este orden.
PASO_CODIGO = {RELEVANCIA: 1, SENTIMIENTO: 2, EMBEDDING: 3}


def llm_policy(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        "SELECT max_intentos,backoff_base_ms,backoff_max_ms,timeout_ms "
        "FROM ops.politica_reintento WHERE operacion=%s", (OPERACION,),
    ).fetchone()
    if (row is None or not 1 <= row["max_intentos"] <= 10 or row["backoff_base_ms"] < 1
            or row["backoff_max_ms"] < row["backoff_base_ms"] or row["timeout_ms"] < 1):
        raise ValueError("La política persistida de q.llm falta o es inválida")
    return row


def embedding_model_id(conn: psycopg.Connection) -> int | None:
    """Modelo de embedding activo del catálogo (uso='embedding'), por prioridad."""
    row = conn.execute(
        "SELECT id FROM cfg.llm_modelo WHERE uso='embedding' AND estado_id=1 "
        "ORDER BY prioridad,id LIMIT 1").fetchone()
    return row["id"] if row else None


class LlmQueue:
    def __init__(self, settings: WorkerSettings,
                 connect: Callable[[], psycopg.Connection] | None = None,
                 provider=None):
        self.settings = settings
        self._connect = connect or self._database_connection
        self.provider = provider or StubLLMProvider()

    def _database_connection(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.database_host, port=self.settings.database_port,
            dbname=self.settings.database_name, user=self.settings.database_user,
            passfile=str(self.settings.database_passfile), row_factory=dict_row,
            connect_timeout=5, application_name="syntra_llm_worker",
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
        """Reencola o cierra lotes cuyo worker perdió el latido."""
        with self._connect() as conn:
            policy = llm_policy(conn)
            tasks = conn.execute(
                "SELECT id,proceso_id,intentos FROM prc.proceso_tarea "
                "WHERE cola=%s AND estado='en_ejecucion' "
                "AND (latido IS NULL OR latido<now()-(%s*interval '1 second')) "
                "ORDER BY id FOR UPDATE SKIP LOCKED",
                (QUEUE, self.settings.lease_seconds),
            ).fetchall()
            for task in tasks:
                delay = retry_delay_ms(task["intentos"], policy["max_intentos"],
                                       policy["backoff_base_ms"], policy["backoff_max_ms"])
                terminal = delay is None
                conn.execute(
                    "UPDATE prc.proceso_tarea SET estado=%s,worker=NULL,latido=NULL,"
                    "disponible_en=now()+(%s*interval '1 millisecond'),"
                    "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,"
                    "error_codigo='worker_interrumpido',error_mensaje='Worker q.llm interrumpido' WHERE id=%s",
                    ("error" if terminal else "en_cola", delay or 0, terminal, task["id"]),
                )
                if terminal:
                    self._aggregate(conn, task["proceso_id"])
                else:
                    conn.execute("UPDATE prc.proceso SET estado='en_cola' WHERE id=%s",
                                 (task["proceso_id"],))
            return len(tasks)

    def claim(self, worker_id: str) -> ClaimedTask | None:
        with self._connect() as conn:
            llm_policy(conn)
            row = conn.execute(
                "WITH candidate AS (SELECT t.id FROM prc.proceso_tarea t "
                "WHERE t.cola=%s AND t.estado='en_cola' AND t.disponible_en<=now() "
                "ORDER BY t.prioridad,t.disponible_en,t.id FOR UPDATE OF t SKIP LOCKED LIMIT 1) "
                "UPDATE prc.proceso_tarea t SET estado='en_ejecucion',intentos=intentos+1,"
                "iniciado_en=COALESCE(iniciado_en,now()),latido=now(),worker=%s "
                "FROM candidate WHERE t.id=candidate.id "
                "RETURNING t.id,t.proceso_id,t.intentos,t.payload",
                (QUEUE, worker_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE prc.proceso SET estado='en_ejecucion',"
                         "iniciado_en=COALESCE(iniciado_en,now()) WHERE id=%s", (row["proceso_id"],))
            return ClaimedTask(row["id"], row["proceso_id"], row["intentos"], row["payload"])

    def job(self, task: ClaimedTask, worker_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT p.cuenta_id,p.medicion_id "
                "FROM prc.proceso_tarea t JOIN prc.proceso p ON p.id=t.proceso_id "
                "WHERE t.id=%s AND t.worker=%s AND t.estado='en_ejecucion' AND t.cola=%s AND p.id=%s",
                (task.id, worker_id, QUEUE, task.process_id),
            ).fetchone()
            if row is None:
                raise ValueError("Tarea de cómputo inválida o sin medición asociada")
            # Prompts congelados de la medición (red_id=0 = general).
            prompts = {item["tipo"]: item["contenido"] for item in conn.execute(
                "SELECT tipo,contenido FROM med.medicion_prompt WHERE medicion_id=%s "
                "AND tipo IN ('relevancia','sentimiento') AND red_id=0", (row["medicion_id"],)
            ).fetchall()}
            modelo = embedding_model_id(conn)
            periodo = task.payload.get("periodo")
            desde = task.payload.get("desde")
            hasta = task.payload.get("hasta")
            if not all(isinstance(v, int) for v in (periodo, desde, hasta)) or hasta < desde:
                raise ValueError("Payload de q.llm sin ventana keyset válida")
            timeout_ms = llm_policy(conn)["timeout_ms"]
            # Solo registros incorporados con algún paso pendiente dentro de la ventana.
            pendientes = conn.execute(
                "SELECT e.registro_id,r.texto,e.st_relevancia,e.st_sentimiento,e.st_embedding "
                "FROM dat.registro_estado e "
                "JOIN dat.registro r ON r.cuenta_id=e.cuenta_id AND r.medicion_id=e.medicion_id "
                "AND r.periodo=e.periodo AND r.registro_id=e.registro_id "
                "WHERE e.cuenta_id=%s AND e.medicion_id=%s AND e.periodo=%s "
                "AND e.registro_id BETWEEN %s AND %s AND e.incorporado AND e.estado_id<>-1 "
                "AND (e.st_relevancia=0 OR e.st_sentimiento=0 OR e.st_embedding=0) "
                "ORDER BY e.registro_id",
                (row["cuenta_id"], row["medicion_id"], periodo, desde, hasta),
            ).fetchall()
            ids = [item["registro_id"] for item in pendientes]
            hashes = self._embedding_hashes(conn, row["cuenta_id"], row["medicion_id"],
                                            periodo, ids, modelo)
            records = [
                {"registro_id": item["registro_id"], "periodo": periodo,
                 "texto": item["texto"], "texto_hash": hashes.get(item["registro_id"]),
                 "estados": {"st_relevancia": item["st_relevancia"],
                             "st_sentimiento": item["st_sentimiento"],
                             "st_embedding": item["st_embedding"]}}
                for item in pendientes
            ]
            return {"cuenta_id": row["cuenta_id"], "medicion_id": row["medicion_id"],
                    "modelo_embedding_id": modelo,
                    "prompt_relevancia": prompts.get("relevancia", ""),
                    "prompt_sentimiento": prompts.get("sentimiento", ""),
                    "timeout_paso_s": timeout_ms / 1000, "records": records}

    @staticmethod
    def _embedding_hashes(conn, cuenta_id, medicion_id, periodo, registro_ids, modelo_id) -> dict:
        """El embedding solo se recalcula si cambió el texto; tolera pgvector ausente."""
        if modelo_id is None:
            return {}
        try:
            with conn.transaction():
                rows = conn.execute(
                    "SELECT registro_id,texto_hash FROM dat.registro_embedding "
                    "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s "
                    "AND registro_id=ANY(%s) AND modelo_id=%s",
                    (cuenta_id, medicion_id, periodo, registro_ids, modelo_id),
                ).fetchall()
            return {item["registro_id"]: item["texto_hash"] for item in rows}
        except psycopg.errors.UndefinedTable:
            return {}

    def _owned(self, conn: psycopg.Connection, task: ClaimedTask, worker_id: str) -> None:
        row = conn.execute(
            "SELECT id FROM prc.proceso_tarea WHERE id=%s AND proceso_id=%s AND cola=%s "
            "AND worker=%s AND estado='en_ejecucion' FOR UPDATE",
            (task.id, task.process_id, QUEUE, worker_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("Se perdió la propiedad de la tarea")

    def save_record(self, task: ClaimedTask, worker_id: str, record: dict,
                    resultados: dict, problemas: list[tuple[str, str]]) -> None:
        with self._connect() as conn:
            timeout = llm_policy(conn)["timeout_ms"]
            conn.execute("SELECT set_config('statement_timeout',%s,true)", (str(timeout),))
            job = conn.execute(
                "SELECT p.cuenta_id,p.medicion_id FROM prc.proceso_tarea t "
                "JOIN prc.proceso p ON p.id=t.proceso_id "
                "WHERE t.id=%s AND t.worker=%s AND t.estado='en_ejecucion'",
                (task.id, worker_id),
            ).fetchone()
            if job is None:
                raise RuntimeError("Se perdió la propiedad de la tarea")
            modelo = embedding_model_id(conn)
            key = (job["cuenta_id"], job["medicion_id"], record["periodo"], record["registro_id"])
            if RELEVANCIA in resultados:
                codigo, pct = resultados[RELEVANCIA]
                conn.execute(
                    "UPDATE dat.registro_estado SET relevancia_ia=%s,relevancia_pct=%s,st_relevancia=%s "
                    "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s",
                    (codigo, pct, OK, *key))
                self._record_ia(conn, key, task.process_id, RELEVANCIA, codigo, pct)
            if SENTIMIENTO in resultados:
                valor = resultados[SENTIMIENTO]
                conn.execute(
                    "UPDATE dat.registro_estado SET sentimiento=%s,sentimiento_origen='i',st_sentimiento=%s "
                    "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s",
                    (valor, OK, *key))
                self._record_ia(conn, key, task.process_id, SENTIMIENTO, valor, None)
            if EMBEDDING in resultados:
                self._save_embedding(conn, key, modelo, resultados[EMBEDDING])
            for paso, codigo_error in problemas:
                columna = {RELEVANCIA: "st_relevancia", SENTIMIENTO: "st_sentimiento",
                           EMBEDDING: "st_embedding"}[paso]
                conn.execute(
                    f"UPDATE dat.registro_estado SET {columna}=%s "
                    "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s",
                    (ERROR, *key))
                conn.execute(
                    "INSERT INTO dat.registro_evento(cuenta_id,medicion_id,periodo,paso,proceso_id,tarea_id,"
                    "intento,estado,codigo_error,mensaje,detalle) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (*key[:3], PASO_CODIGO[paso], task.process_id, task.id, task.attempts, ERROR,
                     f"{paso}_fallido", "El cómputo del paso falló; se conserva el registro",
                     Jsonb({"registro": record["registro_id"], "clase": codigo_error})))

    def _record_ia(self, conn, key, process_id, paso, valor, pct) -> None:
        conn.execute(
            "INSERT INTO dat.registro_ia(cuenta_id,medicion_id,periodo,registro_id,paso,valor,pct,proceso_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (*key, PASO_CODIGO[paso], valor, pct, process_id))

    def _save_embedding(self, conn, key, modelo_id, resultado) -> None:
        vector, texto_hash = resultado
        if modelo_id is None:
            # Sin modelo de embedding en el catálogo: el paso no aplica.
            conn.execute(
                "UPDATE dat.registro_estado SET st_embedding=4 "
                "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s", key)
            return
        if vector == "reutilizado":
            conn.execute(
                "UPDATE dat.registro_estado SET st_embedding=%s "
                "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s",
                (OK, *key))
            return
        try:
            literal = "[" + ",".join(repr(round(float(v), 6)) for v in vector) + "]"
            conn.execute(
                "INSERT INTO dat.registro_embedding(cuenta_id,medicion_id,periodo,registro_id,modelo_id,"
                "texto_hash,embedding) VALUES (%s,%s,%s,%s,%s,%s,%s::halfvec) "
                "ON CONFLICT (cuenta_id,medicion_id,registro_id,periodo,modelo_id) "
                "DO UPDATE SET texto_hash=EXCLUDED.texto_hash,embedding=EXCLUDED.embedding,creado_en=now()",
                (*key, modelo_id, texto_hash, literal))
            conn.execute(
                "UPDATE dat.registro_estado SET st_embedding=%s "
                "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s",
                (OK, *key))
        except psycopg.errors.UndefinedTable:
            # pgvector ausente: el embedding no aplica en este servidor.
            conn.execute(
                "UPDATE dat.registro_estado SET st_embedding=4 "
                "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s", key)

    def finish(self, task: ClaimedTask, worker_id: str) -> None:
        with self._connect() as conn:
            self._owned(conn, task, worker_id)
            conn.execute("UPDATE prc.proceso_tarea SET estado='completado',finalizado_en=now(),"
                         "latido=NULL,worker=NULL,error_codigo=NULL,error_mensaje=NULL WHERE id=%s", (task.id,))
            self._aggregate(conn, task.process_id)
        self._chain_analysis(task.process_id)

    def _chain_analysis(self, process_id: int) -> None:
        """Al completar el cómputo, si se pidieron clusters encadena una corrida q.analisis.

        Los embeddings ya existen (los calcula este mismo cómputo). Idempotente por
        ``idempotencia='analisis-de:<id>'``: solo se encola una corrida por cómputo.
        """
        try:
            with self._connect() as conn:
                proc = conn.execute(
                    "SELECT medicion_id,cuenta_id,estado,opciones FROM prc.proceso WHERE id=%s",
                    (process_id,)).fetchone()
                if proc is None or proc["estado"] != "completado" or proc["cuenta_id"] is None:
                    return
                opciones = (proc["opciones"] or {}).get("al_incorporar") or {}
                if not opciones.get("clusters"):
                    return
                child = conn.execute(
                    "INSERT INTO prc.proceso(medicion_id,cuenta_id,tipo,modo,padre_id,idempotencia,opciones) "
                    "VALUES (%s,%s,'analisis','automatico',%s,%s,%s) "
                    "ON CONFLICT (idempotencia) WHERE idempotencia IS NOT NULL DO NOTHING RETURNING id",
                    (proc["medicion_id"], proc["cuenta_id"], process_id,
                     f"analisis-de:{process_id}", Jsonb({"origen": "computo"}))).fetchone()
                if child is None:
                    return
                conn.execute(
                    "INSERT INTO prc.proceso_tarea(proceso_id,clave,tipo,cola,prioridad,payload) "
                    "VALUES (%s,'corrida','analisis','q.analisis',5,%s) ON CONFLICT (proceso_id,clave) DO NOTHING",
                    (child["id"], Jsonb({})))
                conn.execute("UPDATE prc.proceso SET total=1 WHERE id=%s", (child["id"],))
            logger.info("Encadenada corrida q.analisis del cómputo %s", process_id)
        except psycopg.Error as exc:
            logger.warning("No se encadenó el análisis del cómputo %s; SQLSTATE=%s",
                           process_id, exc.sqlstate or "desconocido")

    def fail(self, task: ClaimedTask, worker_id: str, code: str) -> None:
        with self._connect() as conn:
            policy = llm_policy(conn)
            row = conn.execute("SELECT id FROM prc.proceso_tarea WHERE id=%s AND worker=%s "
                               "AND estado='en_ejecucion' FOR UPDATE", (task.id, worker_id)).fetchone()
            if row is None:
                return
            delay = retry_delay_ms(task.attempts, policy["max_intentos"],
                                   policy["backoff_base_ms"], policy["backoff_max_ms"])
            terminal = delay is None
            safe_code = code if code in {"computo_fallido", "tiempo_agotado"} else "computo_fallido"
            conn.execute("UPDATE prc.proceso_tarea SET estado=%s,worker=NULL,latido=NULL,"
                         "disponible_en=now()+(%s*interval '1 millisecond'),"
                         "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,"
                         "error_codigo=%s,error_mensaje='El cómputo falló; consultar el diagnóstico' "
                         "WHERE id=%s", ("error" if terminal else "en_cola", delay or 0, terminal, safe_code, task.id))
            if terminal:
                self._aggregate(conn, task.process_id)
            else:
                conn.execute("UPDATE prc.proceso SET estado='en_cola',detalle=%s WHERE id=%s",
                             (safe_code, task.process_id))

    def _pulse(self, task: ClaimedTask, worker_id: str, stop: Event) -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                with self._connect() as conn:
                    conn.execute("UPDATE prc.proceso_tarea SET latido=now() WHERE id=%s AND worker=%s "
                                 "AND estado='en_ejecucion'", (task.id, worker_id))
            except psycopg.Error as exc:
                logger.warning("No se renovó el lease de q.llm %s; SQLSTATE=%s",
                               task.id, exc.sqlstate or "desconocido")

    def process(self, task: ClaimedTask, worker_id: str) -> None:
        stop = Event()
        pulse = Thread(target=self._pulse, args=(task, worker_id, stop), daemon=True)
        pulse.start()
        try:
            with self._connect() as conn:
                timeout = llm_policy(conn)["timeout_ms"]
            ComputeRecords(self, self.provider).execute(task, worker_id, timeout)
        except Exception as exc:
            code = "tiempo_agotado" if isinstance(exc, TimeoutError) else "computo_fallido"
            try:
                self.fail(task, worker_id, code)
            except Exception as failure:
                logger.error("No se pudo registrar el fallo de q.llm %s; SQLSTATE=%s",
                             task.id, getattr(failure, "sqlstate", None) or "desconocido")
                return
            logger.warning("Falló cómputo %s; código=%s clase=%s SQLSTATE=%s",
                           task.id, code, type(exc).__name__, getattr(exc, "sqlstate", None) or "no_sql")
        finally:
            stop.set()
            pulse.join(timeout=2)
