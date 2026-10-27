"""Registro del worker de preparación mediante operaciones acotadas a su cola."""

from __future__ import annotations

import psycopg

from app.config import WorkerSettings


class PostgresMeasurementWorkerRegistry:
    def __init__(self, settings: WorkerSettings):
        self.settings = settings

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.database_host, port=self.settings.database_port,
            dbname=self.settings.database_name, user=self.settings.database_user,
            passfile=str(self.settings.database_passfile), connect_timeout=5,
            application_name="syntra_measurement_worker_registry",
        )

    def register(self, worker_id: str, server: str, pid: int) -> None:
        with self._connect() as conn:
            conn.execute("SELECT ops.fn_registrar_worker_mantenimiento(%s,%s,%s,%s)",
                         (worker_id, server, pid, "0.1.0"))

    def heartbeat(self, worker_id: str, active: int) -> None:
        with self._connect() as conn:
            conn.execute("SELECT ops.fn_latido_worker_mantenimiento(%s,%s)", (worker_id, active))

    def unregister(self, worker_id: str) -> None:
        with self._connect() as conn:
            conn.execute("SELECT ops.fn_borrar_worker_mantenimiento(%s)", (worker_id,))
