"""Pruebas sin PostgreSQL de reglas, permisos y unidad de trabajo de Roles."""

from datetime import datetime, timezone

import pytest

from app.modules.roles.application.service import RoleProblem, RoleProblemKind, RoleUseCases, version_tag


class FakeRoles:
    def __init__(self):
        self.rows = {}
        self.next_id = 1

    def name_exists(self, name, exclude_id=None):
        return any(row["nombre"].lower() == name.lower() and row["estado_id"] != -1 and key != exclude_id
                   for key, row in self.rows.items())

    def get(self, role_id, *, for_update=False):
        row = self.rows.get(role_id)
        return dict(row) if row else None

    def create(self, values, permissions, actor_id):
        role_id = self.next_id
        self.next_id += 1
        row = {"id": role_id, **values, "permisos": {module: [action] for module, action in permissions},
               "actualizado_en": datetime.now(timezone.utc)}
        self.rows[role_id] = row
        return dict(row)

    def update(self, role_id, changes, permissions, actor_id):
        row = self.rows[role_id]
        row.update(changes)
        if permissions is not None:
            row["permisos"] = {module: [action] for module, action in permissions}
        row["actualizado_en"] = datetime.now(timezone.utc)
        return dict(row)

    def set_state(self, role_id, state, actor_id):
        return self.update(role_id, {"estado_id": state}, None, actor_id)

    def has_users(self, role_id):
        return False

    def is_assigned_to(self, role_id, user_id):
        return getattr(self, "self_role", None) == role_id


class FakeAudit:
    def __init__(self):
        self.events = []

    def record(self, **kwargs):
        self.events.append(kwargs)


class FakeUow:
    def __init__(self):
        self.roles = FakeRoles()
        self.audit = FakeAudit()
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def commit(self):
        self.commits += 1


def test_create_rejects_unknown_pair_without_writing():
    uow = FakeUow()
    cases = RoleUseCases(uow)
    with pytest.raises(RoleProblem) as caught:
        cases.create({"nombre": "Prueba", "permisos": {"mediciones": ["exportar"]}, "estado_id": 1},
                     1, frozenset({"roles:crear"}), True)
    assert caught.value.kind == RoleProblemKind.VALIDATION
    assert not uow.roles.rows
    assert not uow.audit.events


def test_create_rejects_escalation_without_writing():
    uow = FakeUow()
    cases = RoleUseCases(uow)
    with pytest.raises(RoleProblem) as caught:
        cases.create({"nombre": "Prueba", "permisos": {"clientes": ["crear"]}, "estado_id": 1},
                     1, frozenset({"roles:crear", "clientes:ver"}), True)
    assert caught.value.kind == RoleProblemKind.FORBIDDEN
    assert uow.commits == 0


def test_create_and_edit_write_one_event_each_and_check_etag():
    uow = FakeUow()
    cases = RoleUseCases(uow)
    permissions = frozenset({"roles:crear", "roles:editar", "clientes:ver"})
    row = cases.create({"nombre": "  Equipo  A ", "permisos": {"clientes": ["ver"]},
                        "estado_id": 1, "ver_todas": False}, 1, permissions, False)
    assert row["nombre"] == "Equipo A"
    assert uow.commits == 1 and len(uow.audit.events) == 1
    with pytest.raises(RoleProblem) as caught:
        cases.edit(row["id"], {"descripcion": "Nueva"}, '"obsoleto"', 1, permissions, False)
    assert caught.value.kind == RoleProblemKind.PRECONDITION_FAILED
    changed = cases.edit(row["id"], {"descripcion": "Nueva"}, version_tag(row), 1, permissions, False)
    assert changed["descripcion"] == "Nueva"
    assert uow.commits == 2 and len(uow.audit.events) == 2


def test_actor_cannot_remove_own_role_edit_permission_or_inactivate_role():
    uow = FakeUow()
    cases = RoleUseCases(uow)
    actor_permissions = frozenset({"roles:crear", "roles:editar"})
    row = cases.create({"nombre": "Administrador", "permisos": {"roles": ["editar"]},
                        "estado_id": 1, "ver_todas": True}, 1, actor_permissions, True)
    uow.roles.self_role = row["id"]
    with pytest.raises(RoleProblem) as removal:
        cases.edit(row["id"], {"permisos": {}}, version_tag(row), 1, actor_permissions, True)
    assert removal.value.kind == RoleProblemKind.CONFLICT
    with pytest.raises(RoleProblem) as inactivation:
        cases.change_state(row["id"], 0, 1)
    assert inactivation.value.kind == RoleProblemKind.CONFLICT
    assert uow.commits == 1 and len(uow.audit.events) == 1
