"""Políticas y coordinación de autenticación sin PostgreSQL."""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
import hashlib
import uuid

import pytest

from app.modules.auth.application.service import AuthProblem, AuthUseCases
from app.modules.auth.domain.rules import failed_login, family_expiry


def _service() -> tuple[AuthUseCases, Mock, Mock]:
    store, crypto = Mock(), Mock()
    return AuthUseCases(store, crypto), store, crypto


def test_lockout_policy_preserves_approved_intervals():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert failed_login(3, now) == (4, None)
    assert failed_login(4, now) == (5, now + timedelta(minutes=15))
    assert failed_login(5, now) == (6, now + timedelta(minutes=30))
    assert failed_login(6, now) == (7, now + timedelta(minutes=60))
    assert failed_login(7, now) == (7, now + timedelta(minutes=60))
    assert family_expiry(now, False) == now + timedelta(hours=8)
    assert family_expiry(now, True) == now + timedelta(days=14)


def test_login_coordinates_hash_session_permissions_and_commit():
    service, store, crypto = _service()
    store.lock_login_user.return_value = {
        "id": 8, "password_hash": "hash", "rol_id": 2, "version_token": 3,
        "estado_id": 1, "rol_estado": 1, "bloqueado_hasta": None,
        "intentos_fallidos": 0, "ver_todas": True,
    }
    crypto.verify_password.return_value = True
    crypto.new_refresh.return_value = ("opaque", b"hash")
    crypto.sign_access.return_value = "jwt"
    store.permissions.return_value = ["clientes:ver"]
    issued = service.login(" user@example.test ", "secret", True, "127.0.0.1", "agent")
    assert issued.access_token == "jwt" and issued.refresh_token == "opaque"
    store.lock_login_user.assert_called_once_with("user@example.test")
    crypto.verify_password.assert_called_once_with("hash", "secret")
    store.create_session.assert_called_once()
    assert store.create_session.call_args.args[4] == issued.expires
    assert store.create_session.call_args.args[5:] == ("127.0.0.1", "agent")
    crypto.sign_access.assert_called_once()
    store.commit.assert_called_once()


def test_failed_login_commits_counter_and_keeps_401():
    service, store, crypto = _service()
    store.lock_login_user.return_value = {
        "id": 8, "password_hash": "hash", "estado_id": 1,
        "rol_estado": 1, "bloqueado_hasta": None, "intentos_fallidos": 4,
    }
    crypto.verify_password.return_value = False
    with pytest.raises(AuthProblem) as problem:
        service.login("user@example.test", "wrong", False, None, None)
    assert (problem.value.status, problem.value.detail) == (401, "Credenciales inválidas")
    assert store.failed_login.call_args.args[:2] == (8, 5)
    assert store.failed_login.call_args.args[2] is not None
    store.commit.assert_called_once()


def test_refresh_reuse_revokes_family_and_rejects_token():
    service, store, crypto = _service()
    sid, family = uuid.uuid4(), uuid.uuid4()
    token = f"{sid}.1.secret"
    crypto.refresh_identity.return_value = (sid, 1)
    store.lock_session.return_value = {
        "refresh_hash": hashlib.sha256(token.encode()).digest(),
        "revocado_en": datetime.now(timezone.utc), "familia_id": family,
    }
    store.has_active_successor.return_value = True
    with pytest.raises(AuthProblem) as problem:
        service.refresh(token, None, None)
    assert (problem.value.status, problem.value.detail) == (401, "Refresh revocado")
    store.revoke_family.assert_called_once_with(family)
    store.commit.assert_called_once()


def test_logout_all_revokes_sessions_and_version_in_one_commit():
    service, store, _ = _service()
    sid = uuid.uuid4()
    service.logout(8, sid, True)
    store.revoke_user_sessions.assert_called_once_with(8)
    store.increment_user_version.assert_called_once_with(8)
    store.revoke_session.assert_not_called()
    store.commit.assert_called_once()


def test_inner_layers_do_not_import_http_or_postgres_and_router_has_no_sql():
    backend = Path(__file__).resolve().parents[1]
    module_root = backend / "app" / "modules" / "auth"
    for layer in ("domain", "application"):
        for source in (module_root / layer).glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            assert not any(name and (name.startswith("fastapi") or name.startswith("psycopg") or ".infrastructure" in name) for name in imports), source
    router = ast.parse((backend / "app" / "api" / "routers" / "auth.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Attribute) and node.attr in {"execute", "commit", "rollback"} for node in ast.walk(router))
