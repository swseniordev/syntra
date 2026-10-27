"""Superficie HTTP de Países y seguridad Bearer."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies.paises import country_use_cases
from app.core.identity import Principal, current_user
from app.main import app
from app.modules.paises.application.service import CountryUseCases
from test_country_use_cases import FakeUow


def test_country_routes_are_registered_with_security():
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/paises", "get"), ("/api/v1/paises", "post"),
        ("/api/v1/paises/{id}", "get"), ("/api/v1/paises/{id}", "patch"),
        ("/api/v1/paises/{id}", "delete"),
        ("/api/v1/paises/{id}/restaurar", "post"),
        ("/api/v1/paises/{id}/estado", "post"),
        ("/api/v1/paises/{id}/historial", "get"),
    }
    assert all(method in paths[path] and paths[path][method].get("security") for path, method in expected)


def test_country_api_rejects_unprivileged_and_invalid_payload():
    uow = FakeUow()
    principal = Principal(user={"id": 1}, role={"id": 1, "ver_todas": True},
                          permissions=frozenset(), session_id=uuid4())
    app.dependency_overrides[current_user] = lambda: principal
    app.dependency_overrides[country_use_cases] = lambda: CountryUseCases(uow)
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/paises").status_code == 403
            assert client.post("/api/v1/paises", json={"nombre": "México", "codigo": "MX"}).status_code == 403
        principal = Principal(user={"id": 1}, role={"id": 1, "ver_todas": True},
                              permissions=frozenset({"paises:ver", "paises:crear", "paises:editar"}), session_id=uuid4())
        app.dependency_overrides[current_user] = lambda: principal
        with TestClient(app) as client:
            assert client.post("/api/v1/paises", json={"nombre": "México", "codigo": "mx"}).status_code == 400
            created = client.post("/api/v1/paises", json={"nombre": "México", "codigo": "MX"})
            assert created.status_code == 201 and created.headers["ETag"]
            assert client.patch(f"/api/v1/paises/{created.json()['id']}", json={"nombre": "Nuevo"}).status_code == 428
    finally:
        app.dependency_overrides.clear()
