"""El historial de Clientes usa los eventos reales y el permiso del contrato."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies.auditoria import audit_use_cases
from app.core.identity import Principal, current_user
from app.main import app
from app.modules.auditoria.application.service import AuditUseCases


class Reader:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def history(self, entity_type, entity_id, before, limit):
        self.calls.append((entity_type, entity_id, before, limit))
        return self.rows


def request(permissions, rows, path="/api/v1/clientes/7/historial"):
    reader = Reader(rows)
    app.dependency_overrides[current_user] = lambda: Principal(
        user={"id": 1}, role={"id": 1, "ver_todas": True},
        permissions=frozenset(permissions), session_id=uuid4(),
    )
    app.dependency_overrides[audit_use_cases] = lambda: AuditUseCases(reader)
    try:
        with TestClient(app, base_url="https://127.0.0.1:5173") as client:
            response = client.get(path)
    finally:
        app.dependency_overrides.clear()
    return response, reader


def test_history_registered_protected_and_permission_enforced():
    assert app.openapi()["paths"]["/api/v1/clientes/{id}/historial"]["get"]["security"]
    denied, reader = request({"clientes:ver"}, [])
    assert denied.status_code == 403
    assert not reader.calls


def test_history_empty_and_real_event_with_cursor():
    empty, reader = request({"auditoria:ver"}, [])
    assert empty.status_code == 200 and empty.json() == []
    assert reader.calls == [("Cliente", "7", None, 26)]
    rows = [
        {"id": 9, "fecha": datetime(2026, 10, 21, 12, tzinfo=timezone.utc), "accion": "editar"},
        {"id": 8, "fecha": datetime(2026, 10, 21, 11, tzinfo=timezone.utc), "accion": "crear"},
    ]
    response, reader = request({"auditoria:ver"}, rows, "/api/v1/clientes/7/historial?limite=1")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [9]
    assert response.headers["X-Next-Cursor"]
    assert reader.calls == [("Cliente", "7", None, 2)]


def test_history_rejects_invalid_cursor():
    response, reader = request({"auditoria:ver"}, [], "/api/v1/clientes/7/historial?cursor=invalido")
    assert response.status_code == 400
    assert not reader.calls
