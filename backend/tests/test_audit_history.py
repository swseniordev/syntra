"""Paginación y validación del historial sin PostgreSQL."""

from datetime import datetime, timezone

import pytest

from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor


class FakeReader:
    def __init__(self):
        self.calls = []

    def history(self, entity_type, entity_id, before, limit):
        self.calls.append((entity_type, entity_id, before, limit))
        rows = [
            {"fecha": datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc), "id": 3},
            {"fecha": datetime(2026, 10, 21, 11, 0, tzinfo=timezone.utc), "id": 2},
        ]
        return rows if before is None else [rows[-1]]

    def list(self, filters, before, limit):
        self.calls.append((filters.copy(), before, limit))
        rows = [
            {"fecha": datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc), "id": 3},
            {"fecha": datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc), "id": 2},
            {"fecha": datetime(2026, 10, 21, 11, 0, tzinfo=timezone.utc), "id": 1},
        ]
        return [row for row in rows if before is None or (row["fecha"], row["id"]) < before][:limit]


def test_history_uses_stable_cursor_and_limits_rows():
    reader = FakeReader()
    cases = AuditUseCases(reader)
    first, cursor = cases.history("Rol", "4", None, 1)
    assert [row["id"] for row in first] == [3]
    assert cursor
    second, following = cases.history("Rol", "4", cursor, 1)
    assert [row["id"] for row in second] == [2]
    assert following is None
    assert reader.calls[0] == ("Rol", "4", None, 2)
    assert reader.calls[1][2] == (first[0]["fecha"], 3)


def test_history_rejects_invalid_cursor():
    with pytest.raises(InvalidAuditCursor):
        AuditUseCases(FakeReader()).history("Rol", "4", "incorrecto", 25)


def test_audit_list_keeps_date_id_order_and_binds_cursor_to_filters():
    reader = FakeReader()
    cases = AuditUseCases(reader)
    filters = {"modulo": "clientes", "desde": datetime(2026, 10, 1, tzinfo=timezone.utc)}
    first = cases.list(filters, None, 1)
    second = cases.list(filters, first["siguiente"], 1)
    third = cases.list(filters, second["siguiente"], 1)
    assert [first["items"][0]["id"], second["items"][0]["id"], third["items"][0]["id"]] == [3, 2, 1]
    assert third["siguiente"] is None
    assert reader.calls[1][1] == (first["items"][0]["fecha"], 3)
    with pytest.raises(InvalidAuditCursor):
        cases.list({"modulo": "roles", "desde": filters["desde"]}, first["siguiente"], 1)
