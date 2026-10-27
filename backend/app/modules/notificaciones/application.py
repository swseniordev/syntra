"""Consulta y marcado de notificaciones propias."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class NotificationReader(Protocol):
    def unread_count(self, user_id: int) -> int: ...
    def list(self, user_id: int, only_unread: bool, before: tuple[datetime, int] | None,
             limit: int) -> list[dict[str, Any]]: ...
    def mark_read(self, user_id: int, notification_id: int) -> bool: ...
    def mark_all_read(self, user_id: int) -> None: ...


class Notifications:
    def __init__(self, reader: NotificationReader):
        self.reader = reader

    def list(self, user_id: int, only_unread: bool, before: tuple[datetime, int] | None,
             limit: int) -> tuple[int, list[dict[str, Any]], dict[str, Any] | None]:
        rows = self.reader.list(user_id, only_unread, before, limit + 1)
        page = rows[:limit]
        return self.reader.unread_count(user_id), page, page[-1] if len(rows) > limit else None

    def mark_read(self, user_id: int, notification_id: int) -> bool:
        return self.reader.mark_read(user_id, notification_id)

    def mark_all_read(self, user_id: int) -> None:
        self.reader.mark_all_read(user_id)
