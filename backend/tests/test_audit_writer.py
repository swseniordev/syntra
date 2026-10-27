"""El registro compartido no confirma la transacción ni conserva secretos."""

import pytest

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter, _safe_json


class FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params):
        self.statements.append((statement, params))

    def commit(self):
        raise AssertionError("El escritor de auditoría no debe confirmar la transacción")


def test_redacts_nested_secrets_without_mutating_input():
    source = {"nombre": "Rol", "password_hash": "secreto", "nested": {"token": "secreto", "ok": 1}}
    assert _safe_json(source) == {"nombre": "Rol", "nested": {"ok": 1}}
    assert source["password_hash"] == "secreto"


def test_records_using_caller_transaction():
    conn = FakeConnection()
    PostgresAuditWriter(conn).record(
        actor_id=1, module="usuarios", action="correo_fallido",
        entity_type="Usuario", entity_id="42", after={"estado_id": 1, "password": "secreto"},
        detail="provider_rejected",
    )
    assert len(conn.statements) == 1
    sql, params = conn.statements[0]
    assert "INSERT INTO aud.auditoria" in sql
    assert params[0:5] == (1, "usuarios", "correo_fallido", "Usuario", "42")
    assert params[7].obj == {"estado_id": 1}


def test_rejects_provider_error_text_in_detail():
    conn = FakeConnection()
    with pytest.raises(ValueError):
        PostgresAuditWriter(conn).record(
            actor_id=None, module="usuarios", action="correo_fallido",
            entity_type="Usuario", entity_id="42", detail="SMTP password=secreto",
        )
    assert conn.statements == []
