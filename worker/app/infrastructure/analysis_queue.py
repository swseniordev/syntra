"""Cola durable q.analisis: corrida de clusters por medición.

A diferencia de q.llm (una tarea por lote de registros), el clustering es una
sola tarea sobre todo el dataset de la medición: se cargan los embeddings y se
agrupan de una vez. Reutiliza el esqueleto de claim/latido/recuperación del resto
de colas. Implementa ``AnalysisPort`` contra el esquema ``ana`` + ``dat``.

Prerrequisito operativo (paquete de init): login ``syntra_analysis_worker_login``
sobre ``svc_analisis`` con su pgpass y GRANT. La política de reintento usa
``ops.politica_reintento('analisis')`` si existe, o un respaldo en código.
"""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Callable

import psycopg
from psycopg.rows import dict_row

from app.application.label_clusters import LabelClusters
from app.application.run_analysis import RunAnalysis
from app.config import WorkerSettings
from app.domain.clustering import parse_vector
from app.domain.tasks import ClaimedTask, retry_delay_ms
from app.infrastructure.llm_provider import StubLabelProvider
from app.infrastructure.llm_queue import embedding_model_id

QUEUE = "q.analisis"
OPERACION = "analisis"
HEARTBEAT_SECONDS = 15
# Respaldo si ops.politica_reintento('analisis') no está sembrada.
DEFAULT_POLICY = {"max_intentos": 3, "backoff_base_ms": 60_000,
                  "backoff_max_ms": 300_000, "timeout_ms": 600_000}
logger = logging.getLogger("syntra.worker.analisis")


def analysis_policy(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        "SELECT max_intentos,backoff_base_ms,backoff_max_ms,timeout_ms "
        "FROM ops.politica_reintento WHERE operacion=%s", (OPERACION,),
    ).fetchone()
    if row is None:
        return dict(DEFAULT_POLICY)
    if (not 1 <= row["max_intentos"] <= 10 or row["backoff_base_ms"] < 1
            or row["backoff_max_ms"] < row["backoff_base_ms"] or row["timeout_ms"] < 1):
        raise ValueError("La política persistida de q.analisis es inválida")
    return row


class AnalysisQueue:
    def __init__(self, settings: WorkerSettings,
                 connect: Callable[[], psycopg.Connection] | None = None,
                 labeler=None):
        self.settings = settings
        self._connect = connect or self._database_connection
        self.labeler = labeler or StubLabelProvider()

    def _database_connection(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.database_host, port=self.settings.database_port,
            dbname=self.settings.database_name, user=self.settings.database_user,
            passfile=str(self.settings.database_passfile), row_factory=dict_row,
            connect_timeout=5, application_name="syntra_analysis_worker",
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
            policy = analysis_policy(conn)
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
                    "error_codigo='worker_interrumpido',error_mensaje='Worker q.analisis interrumpido' WHERE id=%s",
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
            analysis_policy(conn)
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

    # ---- AnalysisPort ----------------------------------------------------------------

    def config(self, proceso_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT p.medicion_id,p.cuenta_id,m.num_clusters,m.num_subclusters,m.precluster_activo "
                "FROM prc.proceso p JOIN med.medicion m ON m.id=p.medicion_id "
                "WHERE p.id=%s AND p.estado='en_ejecucion'", (proceso_id,),
            ).fetchone()
            if row is None or row["cuenta_id"] is None:
                return None
            return {"proceso_id": proceso_id, "medicion_id": row["medicion_id"],
                    "cuenta_id": row["cuenta_id"],
                    "k": row["num_clusters"], "k_sub": row["num_subclusters"],
                    "precluster": row["precluster_activo"],
                    "modelo_embedding_id": embedding_model_id(conn)}

    def embeddings(self, cuenta_id: int, medicion_id: int, modelo_id: int | None) -> list[dict]:
        if modelo_id is None:
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT e.periodo,e.registro_id,e.embedding::text AS vector "
                    "FROM dat.registro_embedding e "
                    "JOIN dat.registro_estado s ON s.cuenta_id=e.cuenta_id AND s.medicion_id=e.medicion_id "
                    "AND s.periodo=e.periodo AND s.registro_id=e.registro_id "
                    "WHERE e.cuenta_id=%s AND e.medicion_id=%s AND e.modelo_id=%s "
                    "AND s.incorporado AND s.estado_id<>-1 AND s.st_embedding=2",
                    (cuenta_id, medicion_id, modelo_id),
                ).fetchall()
            except psycopg.errors.UndefinedTable:
                return []  # pgvector ausente
        return [{"periodo": r["periodo"], "registro_id": r["registro_id"],
                 "vector": parse_vector(r["vector"])} for r in rows]

    def create_corrida(self, config: dict, registros: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO ana.corrida(medicion_id,proceso_id,modelo_embedding_id,algoritmo,k,k_sub,"
                "precluster,registros,vigente) VALUES (%s,%s,%s,'kmeans_jerarquico',%s,%s,%s,%s,false) "
                "RETURNING id",
                (config["medicion_id"], config["proceso_id"], config["modelo_embedding_id"],
                 config["k"], config["k_sub"], config["precluster"], registros),
            ).fetchone()
            return row["id"]

    def save_clusters(self, corrida_id: int, arbol: list[dict]) -> tuple[dict, dict]:
        cluster_map: dict[int, int] = {}
        sub_map: dict[tuple[int, int], int] = {}
        with self._connect() as conn:
            for cluster in arbol:
                nombre = f"Cluster {cluster['orden'] + 1}"
                padre = conn.execute(
                    "INSERT INTO ana.cluster(corrida_id,padre_id,nivel,orden,nombre,registros) "
                    "VALUES (%s,NULL,1,%s,%s,%s) RETURNING id",
                    (corrida_id, cluster["orden"], nombre, cluster["registros"]),
                ).fetchone()
                cluster_map[cluster["idx"]] = padre["id"]
                for sub in cluster["subs"]:
                    sub_nombre = f"{cluster['orden'] + 1}.{sub['orden'] + 1}"
                    hijo = conn.execute(
                        "INSERT INTO ana.cluster(corrida_id,padre_id,nivel,orden,nombre,registros) "
                        "VALUES (%s,%s,2,%s,%s,%s) RETURNING id",
                        (corrida_id, padre["id"], sub["orden"], sub_nombre, sub["registros"]),
                    ).fetchone()
                    sub_map[(cluster["idx"], sub["idx"])] = hijo["id"]
        return cluster_map, sub_map

    def assign(self, corrida_id: int, cuenta_id: int, medicion_id: int,
               asignaciones: list[tuple]) -> None:
        with self._connect() as conn:
            conn.cursor().executemany(
                "UPDATE dat.registro_estado SET corrida_id=%s,cluster_id=%s,subcluster_id=%s,st_cluster=2 "
                "WHERE cuenta_id=%s AND medicion_id=%s AND periodo=%s AND registro_id=%s",
                [(corrida_id, cluster_id, subcluster_id, cuenta_id, medicion_id, periodo, registro_id)
                 for periodo, registro_id, cluster_id, subcluster_id in asignaciones],
            )

    def activate(self, corrida_id: int, medicion_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE ana.corrida SET vigente=false WHERE medicion_id=%s AND vigente AND id<>%s",
                         (medicion_id, corrida_id))
            conn.execute("UPDATE ana.corrida SET vigente=true WHERE id=%s", (corrida_id,))

    # ---- LabelPort: etiquetado LLM de clusters y temas -------------------------------

    def label_config(self, corrida_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT c.medicion_id,m.cuenta_id FROM ana.corrida c "
                "JOIN med.medicion m ON m.id=c.medicion_id WHERE c.id=%s", (corrida_id,),
            ).fetchone()
            if row is None or row["cuenta_id"] is None:
                return None
            # Prompts congelados de la medición: 'cluster' nombra, 'temas' consolida.
            prompts = {item["tipo"]: item["contenido"] for item in conn.execute(
                "SELECT tipo,contenido FROM med.medicion_prompt WHERE medicion_id=%s "
                "AND tipo IN ('cluster','temas') AND red_id=0", (row["medicion_id"],)
            ).fetchall()}
            timeout_ms = analysis_policy(conn)["timeout_ms"]
            return {"medicion_id": row["medicion_id"], "cuenta_id": row["cuenta_id"],
                    "prompt_cluster": prompts.get("cluster", ""),
                    "prompt_temas": prompts.get("temas", ""),
                    "timeout_paso_s": timeout_ms / 1000}

    def cluster_samples(self, corrida_id: int, max_per_cluster: int) -> list[dict]:
        """Clusters nivel 1 con una muestra de textos para que el LLM los nombre."""
        with self._connect() as conn:
            clusters = conn.execute(
                "SELECT id,orden,nombre,registros FROM ana.cluster "
                "WHERE corrida_id=%s AND nivel=1 ORDER BY orden", (corrida_id,),
            ).fetchall()
            result: list[dict] = []
            for cluster in clusters:
                samples = [row["texto"] for row in conn.execute(
                    "SELECT r.texto FROM dat.registro_estado e "
                    "JOIN dat.registro r ON r.cuenta_id=e.cuenta_id AND r.medicion_id=e.medicion_id "
                    "AND r.periodo=e.periodo AND r.registro_id=e.registro_id "
                    "WHERE e.corrida_id=%s AND e.cluster_id=%s AND r.texto IS NOT NULL "
                    "ORDER BY e.registro_id LIMIT %s",
                    (corrida_id, cluster["id"], max_per_cluster),
                ).fetchall()]
                result.append({"cluster_id": cluster["id"], "orden": cluster["orden"],
                               "nombre": cluster["nombre"], "registros": cluster["registros"],
                               "samples": samples})
            return result

    def save_cluster_label(self, cluster_id: int, nombre: str, descripcion: str | None) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE ana.cluster SET nombre=%s,descripcion=%s WHERE id=%s",
                         (nombre, descripcion, cluster_id))

    def save_themes(self, corrida_id: int, cuenta_id: int, medicion_id: int,
                    themes: list[dict], orden_to_cluster: dict[int, int]) -> int:
        with self._connect() as conn:
            for tema in themes:
                row = conn.execute(
                    "INSERT INTO ana.tema(corrida_id,nombre,resumen,sentimiento_predominante,riesgo) "
                    "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    (corrida_id, tema["nombre"], tema["resumen"], tema["sentimiento"], tema["riesgo"]),
                ).fetchone()
                cluster_ids = [orden_to_cluster[o] for o in tema["clusters"] if o in orden_to_cluster]
                conn.cursor().executemany(
                    "INSERT INTO ana.cluster_tema(cluster_id,tema_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    [(cluster_id, row["id"]) for cluster_id in cluster_ids])
                # Sella el tema en los registros de esos clusters (nivel 1 o sus subclusters).
                conn.execute(
                    "UPDATE dat.registro_estado SET tema_id=%s "
                    "WHERE corrida_id=%s AND cuenta_id=%s AND medicion_id=%s AND cluster_id=ANY(%s)",
                    (row["id"], corrida_id, cuenta_id, medicion_id, cluster_ids))
            return len(themes)

    # ---- ciclo de tarea --------------------------------------------------------------

    def finish(self, task: ClaimedTask) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE prc.proceso_tarea SET estado='completado',finalizado_en=now(),"
                         "latido=NULL,worker=NULL,error_codigo=NULL,error_mensaje=NULL WHERE id=%s", (task.id,))
            self._aggregate(conn, task.process_id)

    def fail(self, task: ClaimedTask, worker_id: str, code: str) -> None:
        with self._connect() as conn:
            policy = analysis_policy(conn)
            row = conn.execute("SELECT id FROM prc.proceso_tarea WHERE id=%s AND worker=%s "
                               "AND estado='en_ejecucion' FOR UPDATE", (task.id, worker_id)).fetchone()
            if row is None:
                return
            delay = retry_delay_ms(task.attempts, policy["max_intentos"],
                                   policy["backoff_base_ms"], policy["backoff_max_ms"])
            terminal = delay is None
            safe_code = code if code in {"analisis_fallido", "tiempo_agotado"} else "analisis_fallido"
            conn.execute("UPDATE prc.proceso_tarea SET estado=%s,worker=NULL,latido=NULL,"
                         "disponible_en=now()+(%s*interval '1 millisecond'),"
                         "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,"
                         "error_codigo=%s,error_mensaje='El análisis falló; consultar el diagnóstico' "
                         "WHERE id=%s", ("error" if terminal else "en_cola", delay or 0, terminal, safe_code, task.id))
            if terminal:
                self._aggregate(conn, task.process_id)
            else:
                conn.execute("UPDATE prc.proceso SET estado='en_cola',detalle=%s WHERE id=%s",
                             (safe_code, task.process_id))

    def _label(self, process_id: int) -> None:
        """Etiqueta la corrida recién creada por este proceso. Nunca propaga errores:
        un fallo de etiquetado no debe revertir un clustering ya persistido."""
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT id FROM ana.corrida WHERE proceso_id=%s "
                                   "ORDER BY id DESC LIMIT 1", (process_id,)).fetchone()
            if row is None:
                return
            labeled = LabelClusters(self, self.labeler).execute(row["id"])
            if labeled:
                logger.info("Etiquetado de la corrida %s: %s temas", row["id"], labeled)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se completó el etiquetado del proceso %s; clase=%s",
                           process_id, type(exc).__name__)

    def _pulse(self, task: ClaimedTask, worker_id: str, stop: Event) -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                with self._connect() as conn:
                    conn.execute("UPDATE prc.proceso_tarea SET latido=now() WHERE id=%s AND worker=%s "
                                 "AND estado='en_ejecucion'", (task.id, worker_id))
            except psycopg.Error as exc:
                logger.warning("No se renovó el lease de q.analisis %s; SQLSTATE=%s",
                               task.id, exc.sqlstate or "desconocido")

    def process(self, task: ClaimedTask, worker_id: str) -> None:
        stop = Event()
        pulse = Thread(target=self._pulse, args=(task, worker_id, stop), daemon=True)
        pulse.start()
        try:
            total = RunAnalysis(self).execute(task.process_id)
            if total:
                # El etiquetado es un extra: si falla, los clusters siguen válidos.
                self._label(task.process_id)
            self.finish(task)
            if total:
                logger.info("Corrida de clusters del proceso %s: %s registros", task.process_id, total)
        except Exception as exc:
            code = "tiempo_agotado" if isinstance(exc, TimeoutError) else "analisis_fallido"
            try:
                self.fail(task, worker_id, code)
            except Exception as failure:
                logger.error("No se pudo registrar el fallo de q.analisis %s; SQLSTATE=%s",
                             task.id, getattr(failure, "sqlstate", None) or "desconocido")
                return
            logger.warning("Falló análisis %s; código=%s clase=%s SQLSTATE=%s",
                           task.id, code, type(exc).__name__, getattr(exc, "sqlstate", None) or "no_sql")
        finally:
            stop.set()
            pulse.join(timeout=2)
