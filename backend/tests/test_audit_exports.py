"""Reglas de exportación y enlace temporal sin PostgreSQL."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from app.core import security
from app.modules.auditoria.application.export import AuditExports, ExportProblem, ExportProblemKind


class MemoryExportStore:
    def __init__(self):
        self.rows = {}

    def enqueue(self, actor_id, key, filters):
        if key in self.rows:
            row = self.rows[key]
            return row["id"], row["filters"] == filters, row["estado"]
        self.rows[key] = {"id": len(self.rows) + 1, "filters": filters, "estado": "en_cola"}
        return self.rows[key]["id"], True, "en_cola"

    def get(self, process_id):
        return next((row for row in self.rows.values() if row["id"] == process_id), None)


def test_idempotencia_por_usuario_y_filtros():
    store = MemoryExportStore()
    cases = AuditExports(store)
    filters = {"modulo": "clientes", "desde": datetime(2026, 10, 20, tzinfo=timezone.utc)}
    first = cases.enqueue(1, "clave-de-prueba-0001", filters)
    assert cases.enqueue(1, "clave-de-prueba-0001", filters) == first
    store.rows[next(iter(store.rows))]["estado"] = "completado"
    assert cases.enqueue(1, "clave-de-prueba-0001", filters)["estado"] == "completado"
    with pytest.raises(ExportProblem) as changed:
        cases.enqueue(1, "clave-de-prueba-0001", {**filters, "modulo": "usuarios"})
    assert changed.value.kind is ExportProblemKind.CONFLICT
    assert cases.enqueue(2, "clave-de-prueba-0001", filters)["proceso_id"] != first["proceso_id"]


def test_fechas_y_clave_invalidas():
    cases = AuditExports(MemoryExportStore())
    for key, filters in [
        (None, {}),
        ("clave-de-prueba-0001", {"desde": datetime(2026, 10, 20)}),
        ("clave-de-prueba-0001", {"hasta": datetime.now(timezone.utc) + timedelta(days=1)}),
        ("clave-de-prueba-0001", {"desde": datetime(2026, 10, 21, tzinfo=timezone.utc),
                                  "hasta": datetime(2026, 10, 20, tzinfo=timezone.utc)}),
    ]:
        with pytest.raises(ExportProblem) as error:
            cases.enqueue(1, key, filters)
        assert error.value.kind is ExportProblemKind.VALIDATION


def test_enlace_firmado_vincula_sesion_usuario_proceso_y_vence(monkeypatch):
    base = Path(__file__).resolve().parents[1] / ".test-db"
    base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audit_keys_", dir=base) as directory:
        _assert_signed_link(Path(directory), monkeypatch)


def _assert_signed_link(tmp_path: Path, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_file = tmp_path / "jwt.pem"
    key_file.write_bytes(private.private_bytes(serialization.Encoding.PEM,
                                               serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    monkeypatch.setattr(security, "settings", replace(security.settings, jwt_private_key=key_file))
    session = uuid4()
    token = security.sign_audit_download(7, session, 29)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 900
    assert security.verify_audit_download(token, 7, session, 29)
    assert not security.verify_audit_download(token, 8, session, 29)
    assert not security.verify_audit_download(token, 7, uuid4(), 29)
    assert not security.verify_audit_download(token, 7, session, 30)
    expired = jwt.encode({**claims, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
                         private, algorithm="RS256", headers=jwt.get_unverified_header(token))
    assert not security.verify_audit_download(expired, 7, session, 29)
