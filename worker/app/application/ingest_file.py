"""Caso de uso de ingesta por bloques, sin conexión ni rutas físicas."""

from __future__ import annotations

from datetime import date, datetime
import time
from typing import Any, Iterator, Protocol

from app.domain.tasks import ClaimedTask
from app.domain.talkwalker import RejectedRow, map_row


CHUNK_SIZE = 1000


class IngestPort(Protocol):
    def job(self, task: ClaimedTask, worker_id: str) -> dict[str, Any]: ...
    def save_chunk(self, task: ClaimedTask, worker_id: str, valid: list[dict],
                   rejected: list[dict], offset: int, job: dict) -> None: ...
    def finish(self, task: ClaimedTask, worker_id: str) -> None: ...


class SourcePort(Protocol):
    def verify(self, key: str, expected_sha256: bytes) -> None: ...
    def rows(self, key: str, extension: str, encoding: str,
             delimiter: str | None) -> Iterator[dict[str, Any]]: ...


class IngestFile:
    def __init__(self, persistence: IngestPort, source: SourcePort):
        self.persistence = persistence
        self.source = source

    def execute(self, task: ClaimedTask, worker_id: str, timeout_ms: int) -> None:
        job = self.persistence.job(task, worker_id)
        start = time.monotonic()
        self.source.verify(job["key"], job["sha256"])
        if (time.monotonic() - start) * 1000 >= timeout_ms:
            raise TimeoutError("La verificación del archivo excedió el límite operativo")
        valid: list[dict] = []
        rejected: list[dict] = []
        offset = job["offset"]
        index = offset
        for index, raw in enumerate(self.source.rows(job["key"], job["extension"],
                                                     job["encoding"], job["delimiter"]), 1):
            if index <= offset:
                continue
            if (time.monotonic() - start) * 1000 >= timeout_ms:
                raise TimeoutError("La ingesta excedió el límite operativo")
            try:
                parsed = map_row(raw, job["mapping"], job["networks"],
                                 job["timezone"], job["fecha_min"])
                parsed["_fila"] = index
                valid.append(parsed)
            except RejectedRow as exc:
                # El evento persistido permite revisar la fila sin imprimirla en los logs.
                sanitized = {key: value.isoformat() if isinstance(value, (date, datetime)) else value
                             for key, value in raw.items()}
                rejected.append({"row": index, "reason": str(exc), "data": sanitized})
            if len(valid) + len(rejected) >= CHUNK_SIZE:
                self.persistence.save_chunk(task, worker_id, valid, rejected, index, job)
                valid, rejected = [], []
        if valid or rejected or offset == 0:
            self.persistence.save_chunk(task, worker_id, valid, rejected, index, job)
        self.persistence.finish(task, worker_id)
