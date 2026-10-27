"""Reglas y casos de uso de Grupos sin PostgreSQL."""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.grupos.application.service import GroupProblem, GroupProblemKind, GroupUseCases, version_tag
from app.modules.grupos.domain.rules import InvalidGroup, normalize


class GroupsFake:
    def __init__(self):
        self.rows = {}
        self.next_id = 1

    def lock_names(self): pass

    def list(self, query, state, after_id, limit):
        rows = [row.copy() for row in self.rows.values() if query.lower() in row["nombre"].lower()
                and (state == "vigentes" and row["estado_id"] != -1 or state == "activos" and row["estado_id"] == 1
                     or state == "inactivos" and row["estado_id"] == 0 or state == "eliminados" and row["estado_id"] == -1)]
        rows.sort(key=lambda row: row["id"])
        return len(rows), [row for row in rows if after_id is None or row["id"] > after_id][:limit]

    def get(self, group_id, *, for_update=False):
        return self.rows[group_id].copy() if group_id in self.rows else None

    def name_exists(self, name, exclude_id=None):
        return any(row["nombre"].lower() == name.lower() and row["estado_id"] != -1 and row["id"] != exclude_id
                   for row in self.rows.values())

    def references_exist(self, user_ids, account_ids):
        return set(user_ids) <= {1, 2} and set(account_ids) <= {10, 11}

    def create(self, values, actor_id):
        identifier = self.next_id
        self.next_id += 1
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        row = {"id": identifier, "descripcion": None, "usuario_ids": [], "cuenta_ids": [],
               "estado_id": 1, "creado_en": now, "actualizado_en": now,
               "creado_por": actor_id, "actualizado_por": actor_id, **values}
        self.rows[identifier] = row
        return row.copy()

    def update(self, group_id, values, actor_id):
        row = self.rows[group_id]
        row.update(values)
        row["actualizado_en"] += timedelta(microseconds=1)
        row["actualizado_por"] = actor_id
        return row.copy()


class UowFake:
    def __init__(self):
        self.groups = GroupsFake()
        self.events = []
        self.audit = self
        self.commits = 0

    def record(self, **event): self.events.append(event)
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def commit(self): self.commits += 1


def test_group_domain_normalizes_and_validates_ids():
    assert normalize({"nombre": "  Equipo\tNorte ", "usuario_ids": [2, 1]}) == {
        "nombre": "Equipo Norte", "usuario_ids": [1, 2],
    }
    for values in ({"nombre": " \n "}, {"usuario_ids": [1, 1]}, {"cuenta_ids": [0]}, {"cuenta_ids": [True]}):
        with pytest.raises(InvalidGroup):
            normalize(values)


def test_group_case_relations_etag_and_restore():
    uow = UowFake()
    cases = GroupUseCases(uow)
    row = cases.create({"nombre": "Equipo", "usuario_ids": [1], "cuenta_ids": [10]}, 1)
    assert row["cuenta_ids"] == [10] and uow.commits == 1
    with pytest.raises(GroupProblem) as missing:
        cases.edit(row["id"], {"nombre": "Nuevo"}, None, 1)
    assert missing.value.kind is GroupProblemKind.PRECONDITION_REQUIRED
    with pytest.raises(GroupProblem) as stale:
        cases.edit(row["id"], {"nombre": "Nuevo"}, '"stale"', 1)
    assert stale.value.kind is GroupProblemKind.PRECONDITION_FAILED
    changed = cases.edit(row["id"], {"cuenta_ids": [11]}, version_tag(row), 1)
    assert changed["usuario_ids"] == [1] and changed["cuenta_ids"] == [11]
    assert version_tag(changed) != version_tag(row)
    cases.delete(row["id"], 1)
    restored = cases.restore(row["id"], 1)
    assert restored["estado_id"] == 0 and restored["cuenta_ids"] == [11]
    assert [event["action"] for event in uow.events] == ["crear", "editar", "eliminar", "restaurar"]


def test_group_rejects_missing_references_and_duplicate_name():
    cases = GroupUseCases(UowFake())
    cases.create({"nombre": "Equipo"}, 1)
    with pytest.raises(GroupProblem) as duplicate:
        cases.create({"nombre": "equipo"}, 1)
    assert duplicate.value.kind is GroupProblemKind.CONFLICT
    with pytest.raises(GroupProblem) as invalid:
        cases.create({"nombre": "Otro", "cuenta_ids": [999]}, 1)
    assert invalid.value.kind is GroupProblemKind.VALIDATION


def test_group_cursor_is_tied_to_filter():
    cases = GroupUseCases(UowFake())
    cases.create({"nombre": "Uno"}, 1)
    cases.create({"nombre": "Dos"}, 1)
    first = cases.list("", "vigentes", None, None, 1)
    assert len(first["items"]) == 1 and first["siguiente"]
    assert cases.list("", "vigentes", None, first["siguiente"], 1)["items"][0]["nombre"] == "Dos"
    with pytest.raises(GroupProblem):
        cases.list("D", "vigentes", None, first["siguiente"], 1)
