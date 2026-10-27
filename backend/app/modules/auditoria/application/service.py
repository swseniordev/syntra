"""Consulta de eventos por entidad con cursor estable de fecha e id."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime
from typing import Any

from app.modules.auditoria.application.ports import AuditReader


class InvalidAuditCursor(ValueError):
    pass


def _decode(cursor: str | None) -> tuple[datetime, int] | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        date_text, row_id = json.loads(raw)
        date = datetime.fromisoformat(date_text)
        if date.tzinfo is None or not isinstance(row_id, int) or row_id < 1:
            raise ValueError
        return date, row_id
    except (ValueError, TypeError, UnicodeError, binascii.Error, json.JSONDecodeError):
        raise InvalidAuditCursor("Cursor inválido") from None


def _encode(row: dict[str, Any]) -> str:
    raw = json.dumps([row["fecha"].isoformat(), row["id"]], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


class AuditUseCases:
    def __init__(self, reader: AuditReader):
        self.reader = reader

    def history(self, entity_type: str, entity_id: str, cursor: str | None, limit: int) -> tuple[list[dict[str, Any]], str | None]:
        rows = self.reader.history(entity_type, entity_id, _decode(cursor), limit + 1)
        items = rows[:limit]
        following = _encode(items[-1]) if len(rows) > limit else None
        return items, following

    def list(self, filters: dict[str, Any], cursor: str | None, limit: int) -> dict[str, Any]:
        if filters.get("desde") and filters.get("hasta") and filters["desde"] > filters["hasta"]:
            raise ValueError("El inicio del periodo debe ser anterior al fin")
        fingerprint = hashlib.sha256(json.dumps(filters, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]
        marker = None
        if cursor:
            try:
                raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
                digest, date_text, row_id = json.loads(raw)
                date = datetime.fromisoformat(date_text)
                if digest != fingerprint or date.tzinfo is None or not isinstance(row_id, int) or row_id < 1:
                    raise ValueError
                marker = (date, row_id)
            except (ValueError, TypeError, UnicodeError, binascii.Error, json.JSONDecodeError):
                raise InvalidAuditCursor("Cursor inválido para estos filtros") from None
        rows = self.reader.list(filters, marker, limit + 1)
        items = rows[:limit]
        following = None
        if len(rows) > limit:
            raw = json.dumps([fingerprint, items[-1]["fecha"].isoformat(), items[-1]["id"]], separators=(",", ":"))
            following = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        return {"items": items, "siguiente": following}

    def get(self, row_id: int, date: datetime) -> dict[str, Any] | None:
        if date.tzinfo is None:
            raise ValueError("La fecha debe incluir zona horaria")
        return self.reader.get(row_id, date)

    def summary(self, start: datetime, end: datetime) -> dict[str, Any]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Las fechas deben incluir zona horaria")
        if start >= end:
            raise ValueError("El inicio del periodo debe ser anterior al fin")
        return {"desde": start, "hasta": end, **self.reader.summary(start, end)}
