"""Reglas de Usuarios sin PostgreSQL."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.modules.usuarios.application.commands import UserCommands, UserProblem, UserProblemKind
from app.modules.usuarios.domain.rules import InvalidUser, normalize
from app.modules.usuarios.infrastructure.commands_postgres import PostgresUserWriter


class FakeUsers:
    def __init__(self):
        self.row = {"id": 2, "nombre": "Persona", "email": "persona@example.test", "telefono": None,
                    "rol_id": 4, "grupo_ids": [], "estado_id": 1, "version_token": 1,
                    "actualizado_en": datetime.now(timezone.utc)}
        self.tasks = []
        self.revoked = []

    def get(self, _identifier, *, for_update=False):
        return self.row.copy()

    def role_authorized(self, role_id, permissions, ver_todas):
        return role_id == 4 and "usuarios:crear" in permissions

    def groups_exist(self, ids):
        return ids == []

    def create(self, values, _actor):
        self.row.update(values)
        return self.row.copy()

    def update(self, user_id, values, _actor):
        self.row.update(values)
        return self.row.copy()

    def enqueue_password(self, user_id, version, actor_id, reason):
        self.tasks.append((user_id, version, actor_id, reason))
        return 71

    def revoke_sessions(self, user_id):
        self.revoked.append(user_id)


class FakeUow:
    def __init__(self):
        self.users = FakeUsers()
        self.events = []
        self.audit = SimpleNamespace(record=lambda **event: self.events.append(event))
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def commit(self):
        self.committed = True


def test_nombre_correo_grupos_y_opcionales():
    assert normalize({"nombre": " Ana\t María\n Pérez ", "email": " ANA@EXAMPLE.TEST ",
                      "telefono": "  ", "grupo_ids": [3, 1]}) == {
        "nombre": "Ana María Pérez", "email": "ana@example.test", "telefono": None, "grupo_ids": [1, 3]}
    with pytest.raises(InvalidUser):
        normalize({"grupo_ids": [1, 1]})
    with pytest.raises(InvalidUser):
        normalize({"email": "correo inválido"})


def test_alta_activa_encola_sin_secretos_y_audita():
    uow = FakeUow()
    row = UserCommands(uow).create({"nombre": "  Otra   Persona ", "email": " OTRA@EXAMPLE.TEST ",
                                    "rol_id": 4, "grupo_ids": []}, 1, frozenset({"usuarios:crear"}), True)
    assert row["nombre"] == "Otra Persona" and row["email"] == "otra@example.test"
    assert "version_token" not in row and "password_hash" not in row
    assert uow.users.tasks == [(2, 1, 1, "alta")]
    assert uow.events[0]["action"] == "crear" and uow.committed


def test_minimo_privilegio_y_proteccion_de_usuario_propio():
    uow = FakeUow()
    cases = UserCommands(uow)
    with pytest.raises(UserProblem) as denied:
        cases.create({"nombre": "Nuevo", "email": "nuevo@example.test", "rol_id": 1},
                     1, frozenset({"usuarios:crear"}), False)
    assert denied.value.kind is UserProblemKind.FORBIDDEN
    with pytest.raises(UserProblem) as own:
        cases.change_state(2, 0, 2)
    assert own.value.kind is UserProblemKind.VALIDATION
    with pytest.raises(UserProblem) as deletion:
        cases.delete(2, 2)
    assert deletion.value.kind is UserProblemKind.CONFLICT


def test_reenvio_rota_version_revoca_sesiones_y_audita():
    uow = FakeUow()
    assert UserCommands(uow).resend(2, 1) == 71
    assert uow.users.row["version_token"] == 2
    assert uow.users.revoked == [2]
    assert uow.users.tasks == [(2, 2, 1, "reenvio")]
    assert uow.events[0]["detail"] == "correo_credencial_encolado"


def test_mail_task_payload_contains_only_identity_version_and_reason():
    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, statement, parameters):
            self.calls.append((statement, parameters))
            return SimpleNamespace(fetchone=lambda: {"id": 71})

    conn = Connection()
    assert PostgresUserWriter(conn).enqueue_password(2, 4, 1, "reenvio") == 71
    payload = conn.calls[1][1][1].obj
    assert payload == {"usuario_id": 2, "version_esperada": 4, "motivo": "reenvio"}
