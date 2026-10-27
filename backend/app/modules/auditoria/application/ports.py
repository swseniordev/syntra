"""Contrato del registro técnico usado por las operaciones auditadas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class AuditWriter(Protocol):
    def record(
        self,
        *,
        actor_id: int | None,
        module: str,
        action: str,
        entity_type: str,
        entity_id: str | None,
        entity_name: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        detail: str | None = None,
    ) -> None: ...


class AuditReader(Protocol):
    def list(self, filters: dict[str, Any], before: tuple[datetime, int] | None, limit: int) -> list[dict[str, Any]]: ...
    def summary(self, start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]: ...
    def get(self, row_id: int, date: datetime) -> dict[str, Any] | None: ...
    def history(
        self, entity_type: str, entity_id: str, before: tuple[datetime, int] | None, limit: int,
    ) -> list[dict[str, Any]]: ...
