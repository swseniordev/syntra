from app.api.routers.health import health
from app.main import app


def test_health_reports_only_api_availability() -> None:
    assert health() == {"estado": "disponible"}


def test_openapi_documents_public_health_route() -> None:
    schema = app.openapi()

    assert schema["openapi"].startswith("3.")
    assert "/salud" in schema["paths"]
    assert schema["paths"]["/salud"]["get"]["summary"] == "Comprobar disponibilidad de la API"
