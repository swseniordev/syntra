"""Ejecuta consumidores sin conocer PostgreSQL, SMTP ni archivos."""

from concurrent.futures import ThreadPoolExecutor
import logging
import time
from threading import Event

from app.application.ports import Maintenance, TaskConsumer, WorkerRegistry


def run_consumer(consumer: TaskConsumer, registry: WorkerRegistry, worker_id: str, server: str, pid: int,
                 concurrency: int, poll_seconds: float, stop: Event,
                 logger: logging.Logger, maintenance: Maintenance | None = None) -> None:
    registry.register(worker_id, server, pid)
    futures = set()
    last_cleanup = 0.0
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while not stop.is_set():
                for future in list(futures):
                    if future.done():
                        futures.remove(future)
                        try:
                            future.result()
                        except Exception:
                            # No incluir excepciones de integraciones que puedan contener secretos.
                            logger.error("Tarea interrumpida; el recuperador la revisará")
                registry.heartbeat(worker_id, len(futures))
                consumer.recover()
                if maintenance is not None and time.monotonic() - last_cleanup > 3600:
                    maintenance.cleanup()
                    last_cleanup = time.monotonic()
                while len(futures) < concurrency and not stop.is_set():
                    task = consumer.claim(worker_id)
                    if task is None:
                        break
                    futures.add(pool.submit(consumer.process, task, worker_id))
                stop.wait(poll_seconds)
    finally:
        registry.unregister(worker_id)
