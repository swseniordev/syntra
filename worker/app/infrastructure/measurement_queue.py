"""Adaptador PostgreSQL del consumidor de preparación de Mediciones."""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Callable

import psycopg
from psycopg.rows import dict_row

from app.config import WorkerSettings
from app.domain.tasks import ClaimedTask

logger = logging.getLogger("syntra.worker.measurements")
TASK_TYPE = "preparar_medicion"
QUEUE_NAME = "q.mantenimiento"
OPERATION = "preparar_medicion"
TASK_HEARTBEAT_SECONDS = 15


class InvalidMeasurementPolicy(RuntimeError):
    pass


def retry_delay_ms(attempts: int, maximum: int, waits: list[int] | tuple[int, ...]) -> int | None:
    if type(maximum) is not int or maximum < 1 or attempts < 1 or len(waits) != maximum - 1:
        raise InvalidMeasurementPolicy("La política de preparación es inválida")
    if any(type(wait) is not int or wait < 1 for wait in waits):
        raise InvalidMeasurementPolicy("La política de preparación es inválida")
    return None if attempts >= maximum else waits[attempts - 1]


def measurement_waits(policy: dict) -> tuple[int, ...]:
    """Mapea columnas persistidas existentes a la secuencia aprobada de esta operación."""
    maximum = policy.get("max_intentos")
    base = policy.get("backoff_base_ms")
    cap = policy.get("backoff_max_ms")
    if (type(maximum) is not int or maximum != 3
            or type(base) is not int or base < 1
            or type(cap) is not int or cap < base):
        raise InvalidMeasurementPolicy("La política persistida de preparación es inválida")
    return (base, cap)


class MeasurementQueue:
    def __init__(self, settings: WorkerSettings,
                 connect: Callable[[], psycopg.Connection] | None = None):
        self.settings = settings
        self._connect = connect or self._database_connection

    def _database_connection(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.database_host, port=self.settings.database_port,
            dbname=self.settings.database_name, user=self.settings.database_user,
            passfile=str(self.settings.database_passfile), row_factory=dict_row,
            connect_timeout=5, application_name="syntra_measurement_worker",
        )

    @staticmethod
    def _policy(conn: psycopg.Connection) -> dict:
        row = conn.execute(
            "SELECT max_intentos,backoff_base_ms,backoff_max_ms,timeout_ms FROM ops.politica_reintento "
            "WHERE operacion=%s", (OPERATION,),
        ).fetchone()
        if row is None:
            raise InvalidMeasurementPolicy("Falta la política de reintentos de preparación")
        measurement_waits(row)
        if type(row["timeout_ms"]) is not int or row["timeout_ms"] < 1:
            raise InvalidMeasurementPolicy("El límite de tiempo de preparación es inválido")
        return row

    def recover(self) -> int:
        with self._connect() as conn:
            policy = self._policy(conn)
            rows = conn.execute(
                "SELECT id,proceso_id,intentos FROM prc.proceso_tarea WHERE cola=%s AND tipo=%s "
                "AND estado='en_ejecucion' AND (latido IS NULL OR latido < now()-(%s*interval '1 second')) "
                "ORDER BY id FOR UPDATE SKIP LOCKED",
                (QUEUE_NAME, TASK_TYPE, self.settings.lease_seconds),
            ).fetchall()
            for row in rows:
                wait = retry_delay_ms(row["intentos"], policy["max_intentos"], measurement_waits(policy))
                terminal = wait is None
                conn.execute(
                    "UPDATE prc.proceso_tarea SET estado=%s,disponible_en=CASE WHEN %s THEN now() "
                    "ELSE now()+(%s*interval '1 millisecond') END,worker=NULL,latido=NULL,"
                    "finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,error_codigo='worker_interrumpido',"
                    "error_mensaje='La preparación fue interrumpida y se recuperó' WHERE id=%s",
                    ("error" if terminal else "en_cola", terminal, wait or 0, terminal, row["id"]),
                )
                conn.execute(
                    "UPDATE prc.proceso SET estado=%s,finalizado_en=CASE WHEN %s THEN now() ELSE NULL END,"
                    "errores=errores+1,detalle='worker_interrumpido' WHERE id=%s",
                    ("error" if terminal else "en_cola", terminal, row["proceso_id"]),
                )
            return len(rows)

    def claim(self, worker_id: str) -> ClaimedTask | None:
        with self._connect() as conn:
            row = conn.execute(
                """WITH candidate AS (
                     SELECT id FROM prc.proceso_tarea WHERE cola=%s AND tipo=%s AND estado='en_cola'
                       AND disponible_en<=now() ORDER BY prioridad,disponible_en,id
                       FOR UPDATE SKIP LOCKED LIMIT 1)
                   UPDATE prc.proceso_tarea t SET estado='en_ejecucion',intentos=intentos+1,
                     latido=now(),worker=%s FROM candidate WHERE t.id=candidate.id
                   RETURNING t.id,t.proceso_id,t.intentos,t.payload""",
                (QUEUE_NAME, TASK_TYPE, worker_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE prc.proceso SET estado='en_ejecucion',iniciado_en=COALESCE(iniciado_en,now()) WHERE id=%s",
                         (row["proceso_id"],))
            payload = row["payload"]
            if (not isinstance(payload, dict)
                    or type(payload.get("medicion_id")) is not int
                    or type(payload.get("cuenta_id")) is not int
                    or type(payload.get("actor_id")) is not int
                    or type(payload.get("estado_solicitado", 1)) is not int
                    or payload.get("estado_solicitado", 1) not in (0, 1)):
                conn.execute("UPDATE prc.proceso_tarea SET estado='error',finalizado_en=now(),worker=NULL,latido=NULL,"
                             "error_codigo='payload_invalido',error_mensaje='Payload de preparación inválido' WHERE id=%s",
                             (row["id"],))
                conn.execute("UPDATE prc.proceso SET estado='error',finalizado_en=now(),errores=1,detalle='payload_invalido' WHERE id=%s",
                             (row["proceso_id"],))
                return None
            return ClaimedTask(row["id"], row["proceso_id"], row["intentos"], payload)

    def _pulse(self, task: ClaimedTask, worker_id: str, stop: Event) -> None:
        while not stop.wait(TASK_HEARTBEAT_SECONDS):
            try:
                with self._connect() as conn:
                    conn.execute("UPDATE prc.proceso_tarea SET latido=now() WHERE id=%s AND worker=%s "
                                 "AND estado='en_ejecucion'", (task.id, worker_id))
            except psycopg.Error as exc:
                logger.warning("No se renovó el lease de la tarea %s; SQLSTATE=%s", task.id, exc.sqlstate or "desconocido")

    def prepare(self, task: ClaimedTask, worker_id: str) -> None:
        pulse_stop = Event()
        pulse = Thread(target=self._pulse, args=(task, worker_id, pulse_stop), daemon=True)
        pulse.start()
        try:
            with self._connect() as conn:
                policy = self._policy(conn)
                conn.execute("SET LOCAL lock_timeout = '5s'")
                conn.execute("SELECT set_config('statement_timeout',%s,true)", (str(policy["timeout_ms"]),))
                owned = conn.execute("SELECT id FROM prc.proceso_tarea WHERE id=%s AND worker=%s "
                                     "AND estado='en_ejecucion' FOR UPDATE", (task.id, worker_id)).fetchone()
                if owned is None:
                    return
                payload = task.payload
                if type(payload.get("cuenta_id")) is not int or type(payload.get("actor_id")) is not int:
                    raise ValueError("payload_invalido")
                requested_state = payload.get("estado_solicitado", 1)
                if requested_state not in (0, 1):
                    raise ValueError("payload_invalido")
                conn.execute("SELECT ops.fn_preparar_medicion_segura(%s,%s,%s,%s,%s,%s)",
                             (task.id, worker_id, payload["cuenta_id"], payload["medicion_id"],
                              payload["actor_id"], requested_state))
                conn.execute("UPDATE prc.proceso_tarea SET estado='completado',finalizado_en=now(),ok=1,errores=0,"
                             "error_codigo=NULL,error_mensaje=NULL WHERE id=%s AND worker=%s", (task.id, worker_id))
                conn.execute("UPDATE prc.proceso SET estado='completado',finalizado_en=now(),progreso=100,"
                             "procesados=1,ok=1,errores=0,detalle=NULL WHERE id=%s", (task.process_id,))
        finally:
            pulse_stop.set()
            pulse.join(timeout=2)

    def fail(self, task: ClaimedTask, worker_id: str, error_code: str = "preparacion_fallida") -> None:
        safe_code = error_code if error_code in {"preparacion_fallida", "worker_interrumpido", "payload_invalido"} else "preparacion_fallida"
        with self._connect() as conn:
            policy = self._policy(conn)
            row = conn.execute("SELECT id FROM prc.proceso_tarea WHERE id=%s AND worker=%s "
                               "AND estado='en_ejecucion' FOR UPDATE", (task.id, worker_id)).fetchone()
            if row is None:
                return
            wait = retry_delay_ms(task.attempts, policy["max_intentos"], measurement_waits(policy))
            if wait is None:
                conn.execute("UPDATE prc.proceso_tarea SET estado='error',finalizado_en=now(),worker=NULL,latido=NULL,"
                             "error_codigo=%s,error_mensaje='La preparación agotó los intentos configurados' WHERE id=%s",
                             (safe_code, task.id))
                conn.execute("UPDATE prc.proceso SET estado='error',finalizado_en=now(),errores=1,"
                             "detalle=%s WHERE id=%s", (safe_code, task.process_id))
            else:
                conn.execute("UPDATE prc.proceso_tarea SET estado='en_cola',disponible_en=now()+(%s*interval '1 millisecond'),"
                             "worker=NULL,latido=NULL,error_codigo=%s,error_mensaje='La preparación se reintentará según la política' WHERE id=%s",
                             (wait, safe_code, task.id))
                conn.execute("UPDATE prc.proceso SET estado='en_cola',errores=errores+1,detalle=%s WHERE id=%s",
                             (safe_code, task.process_id))

    def process(self, task: ClaimedTask, worker_id: str) -> None:
        from app.application.prepare_measurement import PrepareMeasurement
        try:
            PrepareMeasurement(self).execute(task, worker_id)
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            error_code = "payload_invalido" if isinstance(exc, ValueError) else "preparacion_fallida"
            try:
                self.fail(task, worker_id, error_code)
            except Exception as failure:
                logger.error("No se pudo persistir el resultado de la tarea %s; SQLSTATE=%s",
                             task.id, getattr(failure, "sqlstate", None) or "desconocido")
                return
            logger.warning("Falló la preparación de la tarea %s; SQLSTATE=%s", task.id, sqlstate or "no_sql")
