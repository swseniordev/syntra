from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import sys

import pytest
from pathlib import Path
from psycopg.rows import dict_row

from app.core.security import password_hasher
from app.modules.auth.infrastructure.core_crypto import CoreAuthCrypto
from app.modules.usuarios.application.bootstrap import BootstrapAdmin, BootstrapAdminProblem
from app.modules.usuarios.bootstrap_admin import _read_input


class FakeBootstrapUow:
    def __init__(self, *, role=("Administrador", 1, 67), users=None, fail_audit=False):
        self.role = role
        self.users = list(users or [])
        self.events = []
        self.fail_audit = fail_audit
        self.committed = False
        self.snapshot = None
        self.preflight_result = {
            "database": "syntra", "current_user": "syntra_api_login", "session_user": "syntra_api_login",
            "superuser": False,
            "tables": {"usuario": True, "rol": True, "rol_permiso": True, "auditoria": True},
            "privileges": {"usuario_select": True, "usuario_lock": True,
                            "usuario_insert": True, "auditoria_insert": True},
            "has_users": False,
            "admin_role": {"nombre": "Administrador", "estado_id": 1, "permisos": 67},
        }
        self.audit = SimpleNamespace(record=self._record)

    def __enter__(self):
        self.snapshot = deepcopy((self.users, self.events))
        self.committed = False
        return self

    def __exit__(self, exc_type, _value, _traceback):
        if exc_type is not None or not self.committed:
            self.users, self.events = self.snapshot

    def lock_users(self):
        return None

    def email_exists(self, email):
        return any(row["email"].lower() == email.lower() for row in self.users)

    def has_users(self):
        return bool(self.users)

    def admin_role(self):
        return self.role

    def preflight(self):
        return deepcopy(self.preflight_result)

    def create_admin(self, name, email, password_hash):
        row = {"id": 1, "nombre": name, "email": email, "password_hash": password_hash,
               "rol_id": 1, "estado_id": 1}
        self.users.append(row)
        return {key: value for key, value in row.items() if key != "password_hash"}

    def _record(self, **event):
        if self.fail_audit:
            raise RuntimeError("fallo de auditoría")
        self.events.append(event)

    def commit(self):
        self.committed = True


def test_bootstrap_hash_argon2id_admin_activo_y_auditoria_sin_hash():
    uow = FakeBootstrapUow()
    chosen = "Clave QA elegida 2026!"
    password_hash = password_hasher.hash(chosen)

    identifier = BootstrapAdmin(uow).create("  Admin Syntra ", " ADMIN@EXAMPLE.TEST ", password_hash)

    assert identifier == 1
    assert password_hash.startswith("$argon2id$")
    assert CoreAuthCrypto().verify_password(password_hash, chosen)
    assert uow.users[0]["nombre"] == "Admin Syntra"
    assert uow.users[0]["email"] == "admin@example.test"
    assert (uow.users[0]["rol_id"], uow.users[0]["estado_id"]) == (1, 1)
    assert uow.events[0]["actor_id"] == identifier
    assert uow.events[0]["after"]["rol_id"] == 1
    assert "password_hash" not in repr(uow.events)
    assert uow.committed


def test_bootstrap_es_idempotente_y_no_modifica_usuario_existente():
    uow = FakeBootstrapUow()
    bootstrap = BootstrapAdmin(uow)
    bootstrap.create("Admin", "admin@example.test", password_hasher.hash("Otra clave QA válida"))
    original_hash = uow.users[0]["password_hash"]

    with pytest.raises(BootstrapAdminProblem, match="Ya existe"):
        bootstrap.create("Otro", "admin@example.test", password_hasher.hash("Una clave distinta válida"))

    assert len(uow.users) == 1
    assert uow.users[0]["password_hash"] == original_hash
    assert len(uow.events) == 1


def test_bootstrap_rechaza_cualquier_usuario_preexistente_y_rol_no_aprobado():
    existing = FakeBootstrapUow(users=[{"id": 9, "email": "persona@example.test"}])
    with pytest.raises(BootstrapAdminProblem, match="bootstrap inicial"):
        BootstrapAdmin(existing).create("Admin", "admin@example.test", password_hasher.hash("Clave QA válida 2026"))

    for role in (("Administrador", 0, 67), ("Administrador", 1, 66), None):
        with pytest.raises(BootstrapAdminProblem, match="rol Administrador"):
            BootstrapAdmin(FakeBootstrapUow(role=role)).create(
                "Admin", "admin@example.test", password_hasher.hash("Clave QA válida 2026"),
            )


def test_fallo_de_auditoria_revierte_alta():
    uow = FakeBootstrapUow(fail_audit=True)
    with pytest.raises(RuntimeError, match="fallo de auditoría"):
        BootstrapAdmin(uow).create("Admin", "admin@example.test", password_hasher.hash("Clave QA válida 2026"))
    assert uow.users == []
    assert uow.events == []
    assert not uow.committed


def test_contraseña_se_solicita_con_prompt_oculto_y_no_se_imprime(capsys):
    calls = []
    values = iter(("Admin", "admin@example.test"))

    def hidden(prompt):
        calls.append(prompt)
        return "Clave QA elegida 2026!"

    result = _read_input(lambda _prompt: next(values), hidden)

    assert result == ("Admin", "admin@example.test", "Clave QA elegida 2026!")
    assert calls == ["Contraseña elegida para el administrador: ", "Repetir contraseña: "]
    assert capsys.readouterr().out == ""


def test_el_bootstrap_no_acepta_hashes_de_otro_algoritmo():
    with pytest.raises(BootstrapAdminProblem, match="Argon2id"):
        BootstrapAdmin(FakeBootstrapUow()).create("Admin", "admin@example.test", "plaintext")


def test_prevalidacion_solo_lectura_revisa_identidad_privilegios_y_estado():
    uow = FakeBootstrapUow()
    result = BootstrapAdmin(uow).preflight()
    assert result["ready"] is True
    assert uow.committed is False

    uow = FakeBootstrapUow()
    uow.preflight_result["privileges"]["auditoria_insert"] = False
    assert BootstrapAdmin(uow).preflight()["ready"] is False

    uow = FakeBootstrapUow()
    uow.preflight_result["current_user"] = "postgres"
    assert BootstrapAdmin(uow).preflight()["ready"] is False


def test_prevalidacion_rechaza_insert_por_columna_sin_privilegio_de_bloqueo():
    uow = FakeBootstrapUow()
    uow.preflight_result["privileges"].update({
        "usuario_lock": False,
        "usuario_nombre_insert": True,
        "usuario_email_insert": True,
        "usuario_hash_insert": True,
        "usuario_rol_insert": True,
        "usuario_estado_insert": True,
    })

    result = BootstrapAdmin(uow).preflight()

    assert result["ready"] is False
    assert result["privileges"]["usuario_lock"] is False
    assert result["privileges"]["usuario_nombre_insert"] is True


def test_modo_check_no_solicita_credenciales_ni_crea_usuario(monkeypatch, capsys):
    from app.modules.usuarios import bootstrap_admin as command

    monkeypatch.setattr(sys, "argv", ["bootstrap_admin", "--check"])
    monkeypatch.setattr(command, "_run_preflight", lambda: {"ready": True})
    monkeypatch.setattr(command, "_print_preflight", lambda _result: None)
    monkeypatch.setattr(command, "_read_input", lambda: pytest.fail("No debe pedir credenciales en --check"))

    command.main()

    assert "PREVALIDACIÓN APROBADA" in capsys.readouterr().out


def test_comando_usa_passfile_configurado_y_rol_api_sin_dependencia_de_appdata(monkeypatch, capsys):
    from app.modules.usuarios import bootstrap_admin as command

    class Cursor:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self):
            self.calls = []
            self.committed = False
            self.rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, _value, _traceback):
            if exc_type is not None:
                self.rolled_back = True

        def execute(self, statement, parameters=()):
            self.calls.append((statement, parameters))
            if statement == "SET TRANSACTION READ ONLY":
                return Cursor()
            if "current_database() AS database" in statement:
                return Cursor({"database": "syntra", "current_user": "syntra_api_login",
                               "session_user": "syntra_api_login", "superuser": False})
            if "to_regclass('seg.usuario')" in statement:
                return Cursor({"usuario": True, "rol": True, "rol_permiso": True, "auditoria": True})
            if "has_schema_privilege" in statement:
                return Cursor({"seg_usage": True, "aud_usage": True, "usuario_select": True,
                               "usuario_lock": True,
                               "usuario_nombre_insert": True, "usuario_email_insert": True,
                               "usuario_hash_insert": True, "usuario_rol_insert": True,
                               "usuario_estado_insert": True, "rol_select": True,
                               "permiso_select": True, "auditoria_insert": True})
            if "SELECT EXISTS" in statement:
                return Cursor({"has_users": False, "email_exists": False})
            if "FROM seg.rol r LEFT JOIN" in statement:
                return Cursor({"nombre": "Administrador", "estado_id": 1, "permisos": 67})
            if "INSERT INTO seg.usuario" in statement:
                return Cursor({"id": 5, "nombre": "Admin QA", "email": "admin@example.test",
                               "rol_id": 1, "estado_id": 1})
            return Cursor()

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    connections = [Connection(), Connection()]
    all_connections = list(connections)
    connect_args = {}
    monkeypatch.setattr(command, "settings", SimpleNamespace(
        database_host="host.docker.internal", database_port=5432, database_name="syntra",
        database_user="syntra_api_login", database_passfile=__import__("pathlib").Path("/run/secrets/api.pgpass"),
    ))
    monkeypatch.setattr(command, "_read_input", lambda: ("Admin QA", "admin@example.test", "Clave privada QA 2026!"))
    monkeypatch.setattr(sys, "argv", ["bootstrap_admin"])
    def connect(**kwargs):
        connect_args.update(kwargs)
        return connections.pop(0)

    monkeypatch.setattr(command.psycopg, "connect", connect)
    monkeypatch.delenv("APPDATA", raising=False)

    command.main()

    assert connect_args == {
        "host": "host.docker.internal", "port": 5432, "dbname": "syntra", "user": "syntra_api_login",
        "passfile": str(Path("/run/secrets/api.pgpass")), "connect_timeout": 5,
        "application_name": "syntra_admin_bootstrap", "row_factory": dict_row,
    }
    preflight_conn, conn = all_connections
    insert_params = next(params for sql, params in conn.calls if "INSERT INTO seg.usuario" in sql)
    assert insert_params[:2] == ("Admin QA", "admin@example.test")
    assert insert_params[2].startswith("$argon2id$")
    assert preflight_conn.calls[0][0] == "SET TRANSACTION READ ONLY"
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "LOCK"))
                   for sql, _ in preflight_conn.calls)
    assert preflight_conn.rolled_back
    assert conn.committed and not conn.rolled_back
    output = capsys.readouterr().out
    assert "id=5" in output and "Clave privada QA 2026!" not in output
    assert insert_params[2] not in output
