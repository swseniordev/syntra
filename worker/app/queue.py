"""Cola PostgreSQL de correo: bloqueo, reintento y recuperación."""

from __future__ import annotations

import logging
import secrets
from typing import Callable

from argon2 import PasswordHasher
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import WorkerSettings
from app.application.ports import MailProvider
from app.domain.tasks import ClaimedTask, mail_user_eligible, retry_delay_ms

logger = logging.getLogger("syntra.worker.mail")
hasher = PasswordHasher()


class TaskQueue:
    def __init__(self, settings: WorkerSettings, queue_name: str, task_type: str, operation: str,
                 connect: Callable[[], psycopg.Connection] | None = None):
        self.settings = settings
        self._connect = connect or self._database_connection
        self.queue_name = queue_name
        self.task_type = task_type
        self.operation = operation

    def _database_connection(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.database_host, port=self.settings.database_port,
            dbname=self.settings.database_name, user=self.settings.database_user,
            passfile=str(self.settings.database_passfile), row_factory=dict_row,
            connect_timeout=5, application_name="syntra_" + self.settings.queue.replace("q.", "") + "_worker",
        )

    def policy(self, conn: psycopg.Connection) -> dict:
        row = conn.execute(
            "SELECT max_intentos,backoff_base_ms,backoff_max_ms,timeout_ms "
            "FROM ops.politica_reintento WHERE operacion=%s", (self.operation,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Falta la política de reintentos del worker")
        return row

    def recover(self) -> int:
        with self._connect() as conn:
            policy = self.policy(conn)
            rows = conn.execute(
                "SELECT id,proceso_id,intentos FROM prc.proceso_tarea "
                "WHERE cola=%s AND tipo=%s AND estado='en_ejecucion' "
                "AND latido < now() - (%s * interval '1 second') FOR UPDATE SKIP LOCKED",
                (self.queue_name, self.task_type, self.settings.lease_seconds),
            ).fetchall()
            for row in rows:
                retry = retry_delay_ms(row["intentos"], policy["max_intentos"],
                                       policy["backoff_base_ms"], policy["backoff_max_ms"]) is not None
                conn.execute(
                    "UPDATE prc.proceso_tarea SET estado=%s,disponible_en=now(),worker=NULL,"
                    "error_codigo='worker_interrumpido',error_mensaje='La tarea superó el plazo de recuperación' WHERE id=%s",
                    ("en_cola" if retry else "error", row["id"]),
                )
                conn.execute("UPDATE prc.proceso SET estado=%s,finalizado_en=CASE WHEN %s THEN finalizado_en ELSE now() END,"
                             "errores=errores+1,detalle='worker_interrumpido' WHERE id=%s",
                             ("en_cola" if retry else "error", retry, row["proceso_id"]),
                )
            return len(rows)

    def claim(self, worker_id: str) -> ClaimedTask | None:
        with self._connect() as conn:
            row = conn.execute(
                """WITH candidate AS (
                     SELECT id FROM prc.proceso_tarea
                      WHERE cola=%s AND tipo=%s
                        AND estado='en_cola' AND disponible_en<=now()
                      ORDER BY prioridad,disponible_en,id FOR UPDATE SKIP LOCKED LIMIT 1)
                   UPDATE prc.proceso_tarea t
                      SET estado='en_ejecucion',intentos=intentos+1,latido=now(),worker=%s
                     FROM candidate WHERE t.id=candidate.id
                   RETURNING t.id,t.proceso_id,t.intentos,t.payload""",
                (self.queue_name, self.task_type, worker_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE prc.proceso SET estado='en_ejecucion',iniciado_en=COALESCE(iniciado_en,now()) WHERE id=%s",
                (row["proceso_id"],),
            )
            return ClaimedTask(row["id"], row["proceso_id"], row["intentos"], row["payload"])

    def _finish(self, conn: psycopg.Connection, task: ClaimedTask, worker_id: str,
                state: str, reason: str | None = None) -> None:
        row = conn.execute(
            "UPDATE prc.proceso_tarea SET estado=%s,finalizado_en=now(),error_codigo=%s,"
            "error_mensaje=%s,ok=%s,errores=%s WHERE id=%s AND worker=%s AND estado='en_ejecucion' RETURNING id",
            (state, reason, reason, int(state == "completado"), int(state == "error"), task.id, worker_id),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE prc.proceso SET estado=%s,finalizado_en=now(),progreso=100,procesados=1,"
                "ok=%s,errores=%s,detalle=%s WHERE id=%s",
                (state, int(state == "completado"), int(state == "error"), reason, task.process_id),
            )

class MailQueue(TaskQueue):
    def __init__(self, settings: WorkerSettings, provider: MailProvider | None,
                 connect: Callable[[], psycopg.Connection] | None = None):
        super().__init__(settings, "q.notificaciones", "correo_acceso", "correo_acceso", connect)
        self.provider = provider

    def _prepare(self, task: ClaimedTask, worker_id: str) -> tuple[str, str, float, str] | None:
        with self._connect() as conn:
            policy = self.policy(conn)
            locked = conn.execute(
                "SELECT id FROM prc.proceso_tarea WHERE id=%s AND worker=%s AND estado='en_ejecucion' FOR UPDATE",
                (task.id, worker_id),
            ).fetchone()
            if locked is None:
                return None
            user_id = task.payload.get("usuario_id")
            expected = task.payload.get("version_esperada")
            reason = task.payload.get("motivo", "alta")
            if type(user_id) is not int or type(expected) is not int or reason not in ("alta", "reenvio"):
                self._finish(conn, task, worker_id, "error", "payload_invalido")
                return None
            user = conn.execute(
                "SELECT id,email,estado_id,version_token FROM seg.usuario WHERE id=%s FOR UPDATE", (user_id,),
            ).fetchone()
            if not mail_user_eligible(user, expected):
                self._finish(conn, task, worker_id, "cancelado", "usuario_no_elegible")
                return None
            password = secrets.token_urlsafe(24)
            hash_value = hasher.hash(password)
            next_version = expected + 1
            conn.execute(
                "UPDATE seg.usuario SET password_hash=%s,version_token=%s,actualizado_en=clock_timestamp() WHERE id=%s",
                (hash_value, next_version, user_id),
            )
            conn.execute("UPDATE seg.sesion SET revocado_en=now() WHERE usuario_id=%s AND revocado_en IS NULL", (user_id,))
            conn.execute(
                "UPDATE prc.proceso_tarea SET payload=%s,latido=now() WHERE id=%s",
                (Jsonb({"usuario_id": user_id, "version_esperada": next_version, "motivo": reason}), task.id),
            )
            return user["email"], password, policy["timeout_ms"] / 1000, reason

    def prepare(self, task: ClaimedTask, worker_id: str) -> tuple[str, str, float, str] | None:
        return self._prepare(task, worker_id)

    def deliver(self, recipient: str, password: str, timeout: float, reason: str) -> None:
        if self.provider is None:
            raise RuntimeError("El proveedor de correo no está configurado")
        self.provider.send_password(recipient, password, timeout, reason)

    def fail(self, task: ClaimedTask, worker_id: str) -> None:
        with self._connect() as conn:
            policy = self.policy(conn)
            locked = conn.execute(
                "SELECT id,payload FROM prc.proceso_tarea WHERE id=%s AND worker=%s "
                "AND estado='en_ejecucion' FOR UPDATE", (task.id, worker_id),
            ).fetchone()
            if locked is None:
                return
            user_id = locked["payload"].get("usuario_id")
            conn.execute(
                "INSERT INTO aud.auditoria(usuario_id,modulo,accion,entidad_tipo,entidad_id,detalle) "
                "VALUES (NULL,'usuarios','error_correo','Usuario',%s,'correo_proveedor_fallido')",
                (str(user_id),),
            )
            wait_ms = retry_delay_ms(task.attempts, policy["max_intentos"],
                                     policy["backoff_base_ms"], policy["backoff_max_ms"])
            if wait_ms is not None:
                conn.execute(
                    "UPDATE prc.proceso_tarea SET estado='en_cola',disponible_en=now()+(%s*interval '1 millisecond'),"
                    "worker=NULL,error_codigo='correo_proveedor_fallido',error_mensaje='No se pudo entregar el correo' WHERE id=%s",
                    (wait_ms, task.id),
                )
                conn.execute("UPDATE prc.proceso SET estado='en_cola',errores=errores+1,"
                             "detalle='correo_proveedor_fallido' WHERE id=%s", (task.process_id,))
            else:
                self._finish(conn, task, worker_id, "error", "correo_proveedor_fallido")
        logger.warning("Falló la entrega de la tarea de correo %s; se registró para reintento o error", task.id)

    def complete(self, task: ClaimedTask, worker_id: str) -> None:
        with self._connect() as conn:
            self._finish(conn, task, worker_id, "completado")

    def process(self, task: ClaimedTask, worker_id: str) -> None:
        from app.application.send_access_mail import SendAccessMail
        SendAccessMail(self).execute(task, worker_id)
