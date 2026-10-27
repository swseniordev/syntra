"""Caso de uso para delegar la preparación de una medición al puerto durable."""

from __future__ import annotations

from typing import Protocol

from app.domain.tasks import ClaimedTask


class MeasurementPreparer(Protocol):
    def prepare(self, task: ClaimedTask, worker_id: str) -> None: ...


class PrepareMeasurement:
    def __init__(self, preparer: MeasurementPreparer):
        self.preparer = preparer

    def execute(self, task: ClaimedTask, worker_id: str) -> None:
        self.preparer.prepare(task, worker_id)
