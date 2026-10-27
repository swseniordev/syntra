"""Caso de uso de envío de acceso, sin SQL ni implementación SMTP."""

from typing import Protocol

from app.domain.tasks import ClaimedTask


class AccessMailAdapter(Protocol):
    def prepare(self, task: ClaimedTask, worker_id: str) -> tuple[str, str, float, str] | None: ...
    def deliver(self, recipient: str, password: str, timeout: float, reason: str) -> None: ...
    def complete(self, task: ClaimedTask, worker_id: str) -> None: ...
    def fail(self, task: ClaimedTask, worker_id: str) -> None: ...


class SendAccessMail:
    def __init__(self, adapter: AccessMailAdapter):
        self.adapter = adapter

    def execute(self, task: ClaimedTask, worker_id: str) -> None:
        prepared = self.adapter.prepare(task, worker_id)
        if prepared is None:
            return
        recipient, password, timeout, reason = prepared
        try:
            self.adapter.deliver(recipient, password, timeout, reason)
        except Exception:
            self.adapter.fail(task, worker_id)
            return
        finally:
            password = ""
        self.adapter.complete(task, worker_id)
