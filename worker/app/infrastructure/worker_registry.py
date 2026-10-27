"""Registro y latido del proceso worker en PostgreSQL."""

import psycopg

from app.config import WorkerSettings


class PostgresWorkerRegistry:
    def __init__(self, settings: WorkerSettings):
        self.settings = settings

    def _connect(self):
        return psycopg.connect(
            host=self.settings.database_host, port=self.settings.database_port,
            dbname=self.settings.database_name, user=self.settings.database_user,
            passfile=str(self.settings.database_passfile), connect_timeout=5,
            application_name="syntra_" + self.settings.queue.replace("q.", "") + "_worker",
        )

    def register(self, worker_id: str, server: str, pid: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ops.worker(id,servidor,colas,pid,version,tareas_en_curso) "
                "VALUES (%s,%s,ARRAY[%s],%s,'0.1.0',0) "
                "ON CONFLICT (id) DO UPDATE SET latido=now(),tareas_en_curso=0",
                (worker_id, server, self.settings.queue, pid),
            )

    def heartbeat(self, worker_id: str, active: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE ops.worker SET latido=now(),tareas_en_curso=%s WHERE id=%s", (active, worker_id))

    def unregister(self, worker_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM ops.worker WHERE id=%s", (worker_id,))
