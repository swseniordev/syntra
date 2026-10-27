"""Composición y arranque de los consumidores independientes."""

import logging
import os
import signal
import socket
from threading import Event
from uuid import uuid4

from app.application.ports import TaskConsumer, WorkerRegistry
from app.application.runner import run_consumer
from app.config import WorkerSettings
from app.infrastructure.worker_registry import PostgresWorkerRegistry
from app.infrastructure.measurement_queue import MeasurementQueue
from app.infrastructure.measurement_worker_registry import PostgresMeasurementWorkerRegistry
from app.infrastructure.ingest_queue import IngestQueue
from app.infrastructure.ingest_worker_registry import PostgresIngestWorkerRegistry
from app.mail import StartTlsMailProvider
from app.mail_template import MailTemplate
from app.queue import MailQueue
from app.reports import ReportQueue


def _mail_consumer(settings: WorkerSettings) -> MailQueue:
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_from or not settings.smtp_password_file.is_file():
        raise ValueError("La configuración SMTP debe estar completa antes de consumir tareas de correo")
    provider = StartTlsMailProvider(settings.smtp_host, settings.smtp_port, settings.smtp_user,
                                    settings.smtp_password_file, settings.smtp_from,
                                    MailTemplate.from_file(settings.mail_template_file))
    return MailQueue(settings, provider)


CONSUMERS = {
    "q.reportes": ReportQueue,
    "q.notificaciones": _mail_consumer,
    "q.mantenimiento": MeasurementQueue,
    "q.ingesta": IngestQueue,
}


def run(stop_event: Event | None = None, queue: TaskConsumer | None = None,
        registry: WorkerRegistry | None = None) -> None:
    settings = WorkerSettings.from_environment()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger = logging.getLogger("syntra.worker")
    stop = stop_event or Event()
    if stop_event is None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda _signum, _frame: stop.set())
    queue = queue or CONSUMERS[settings.queue](settings)
    if registry is None:
        registry = (PostgresMeasurementWorkerRegistry(settings) if settings.queue == "q.mantenimiento"
                    else PostgresIngestWorkerRegistry(settings) if settings.queue == "q.ingesta"
                    else PostgresWorkerRegistry(settings))
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{settings.queue}:{uuid4().hex[:8]}"
    logger.info("Worker %s iniciado; concurrencia=%s", settings.queue, settings.concurrency)
    try:
        run_consumer(queue, registry, worker_id, socket.gethostname(), os.getpid(), settings.concurrency,
                     settings.poll_seconds, stop, logger,
                     queue if settings.queue == "q.reportes" else None)
    finally:
        logger.info("Worker detenido")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
