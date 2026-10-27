"""Superficie HTTP protegida de Roles."""

from uuid import uuid4
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.dependencies.roles import role_use_cases
from app.api.dependencies.auditoria import audit_use_cases
from app.core.identity import Principal, current_user
from app.main import app
from app.modules.roles.application.service import RoleUseCases
from app.modules.auditoria.application.service import AuditUseCases

from test_role_use_cases import FakeUow


def test_role_routes_are_registered_with_bearer_security():
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        ("/api/v1/roles", "get"), ("/api/v1/roles", "post"),
        ("/api/v1/roles/catalogo-permisos", "get"),
        ("/api/v1/roles/{id}", "get"), ("/api/v1/roles/{id}", "patch"),
        ("/api/v1/roles/{id}", "delete"),
        ("/api/v1/roles/{id}/restaurar", "post"),
        ("/api/v1/roles/{id}/estado", "post"),
        ("/api/v1/roles/{id}/historial", "get"),
    }
    assert all(method in paths[path] for path, method in expected)
    assert all(paths[path][method].get("security") for path, method in expected)


def _client(permissions: frozenset[str]):
    uow = FakeUow()
    principal = Principal(
        user={"id": 1}, role={"id": 1, "ver_todas": True},
        permissions=permissions, session_id=uuid4(),
    )
    app.dependency_overrides[current_user] = lambda: principal
    app.dependency_overrides[role_use_cases] = lambda: RoleUseCases(uow)
    return TestClient(app, base_url="https://127.0.0.1:5173"), uow


def test_role_api_rejects_missing_permission():
    client, _ = _client(frozenset())
    try:
        with client:
            response = client.get("/api/v1/roles")
        assert response.status_code == 403
        assert response.json()["status"] == 403
    finally:
        app.dependency_overrides.clear()


def test_role_api_rejects_unknown_pair_and_allows_catalog_with_permission():
    client, uow = _client(frozenset({"roles:crear", "roles:ver"}))
    uow.roles.catalog = lambda: [{"modulo": "clientes", "accion": "ver", "modulo_nombre": "Clientes", "accion_nombre": "Ver"}]
    try:
        with client:
            catalog = client.get("/api/v1/roles/catalogo-permisos")
            response = client.post("/api/v1/roles", json={
                "nombre": "Prueba", "permisos": {"mediciones": ["exportar"]},
            })
        assert catalog.status_code == 200
        assert response.status_code == 400
        assert not uow.roles.rows
    finally:
        app.dependency_overrides.clear()


def test_role_history_requires_audit_permission_and_returns_real_reader_rows():
    class Reader:
        def history(self, entity_type, entity_id, before, limit):
            assert (entity_type, entity_id, before, limit) == ("Rol", "7", None, 26)
            return [{"id": 2, "fecha": datetime(2026, 10, 21, tzinfo=timezone.utc),
                     "modulo": "roles", "accion": "editar", "entidad_tipo": "Rol", "entidad_id": "7"}]

    client, _ = _client(frozenset({"roles:ver"}))
    app.dependency_overrides[audit_use_cases] = lambda: AuditUseCases(Reader())
    try:
        with client:
            denied = client.get("/api/v1/roles/7/historial")
        assert denied.status_code == 403
    finally:
        app.dependency_overrides.clear()

    client, _ = _client(frozenset({"auditoria:ver"}))
    app.dependency_overrides[audit_use_cases] = lambda: AuditUseCases(Reader())
    try:
        with client:
            response = client.get("/api/v1/roles/7/historial")
        assert response.status_code == 200
        assert response.json()[0]["accion"] == "editar"
    finally:
        app.dependency_overrides.clear()
