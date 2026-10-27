"""Caso de uso de exportación: coordina lease, generación y resultado."""

import logging
import time
from threading import Event, Thread
from typing import Callable, Protocol

from app.domain.tasks import AuditReportRequest, ClaimedTask

logger = logging.getLogger("syntra.worker.report")


class ReportAdapter(Protocol):
    def load(self, task: ClaimedTask) -> tuple[AuditReportRequest, int]: ...
    def render(self, task: ClaimedTask, request: AuditReportRequest,
               deadline: float) -> tuple[int, object | None]: ...
    def publish(self, task: ClaimedTask, worker_id: str, count: int, staged: object | None) -> bool: ...
    def refresh_lease(self, task: ClaimedTask, worker_id: str) -> bool: ...
    def fail(self, task: ClaimedTask, worker_id: str) -> None: ...


class ExportAuditReport:
    def __init__(self, adapter: ReportAdapter, clock: Callable[[], float] = time.monotonic):
        self.adapter = adapter
        self.clock = clock

    def execute(self, task: ClaimedTask, worker_id: str) -> None:
        stop = Event()
        deadline: float | None = None

        def pulse() -> None:
            while not stop.wait(15):
                if deadline is not None and self.clock() >= deadline:
                    # Dejar vencer el lease permite recuperar una escritura bloqueada.
                    return
                try:
                    if not self.adapter.refresh_lease(task, worker_id):
                        return
                except Exception:
                    # Sin renovación, la recuperación por lease decide el siguiente intento.
                    return

        heartbeat = Thread(target=pulse, daemon=True)
        heartbeat.start()
        phase = "load"
        try:
            request, timeout_ms = self.adapter.load(task)
            deadline = self.clock() + timeout_ms / 1000
            phase = "render"
            count, staged = self.adapter.render(task, request, deadline)
            if self.clock() >= deadline:
                raise TimeoutError("Se agotó el tiempo de generación")
            phase = "publish"
            self.adapter.publish(task, worker_id, count, staged)
        except Exception as exc:
            # Solo fase y clase: no exponer consultas, filtros, rutas ni contenido.
            logger.error("Falló la tarea de reporte %s en %s (%s)", task.id, phase, type(exc).__name__)
            self.adapter.fail(task, worker_id)
        finally:
            stop.set()
            heartbeat.join(timeout=1)
