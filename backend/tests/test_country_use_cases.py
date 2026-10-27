"""Reglas de Países sin conexión PostgreSQL."""

from datetime import datetime, timezone, timedelta

import pytest

from app.modules.paises.application.service import CountryProblem, CountryProblemKind, CountryUseCases, version_tag
from app.modules.paises.domain.rules import InvalidCountry, normalize


class FakeCountries:
    def __init__(self):
        self.rows = {}
        self.next_id = 1

    def list(self, query, state, after_id, limit):
        rows = [row for row in self.rows.values() if
                (state == "vigentes" and row["estado_id"] != -1 or state == "activos" and row["estado_id"] == 1
                 or state == "inactivos" and row["estado_id"] == 0 or state == "eliminados" and row["estado_id"] == -1)
                and query.lower() in (row["nombre"] + row["codigo"]).lower()]
        rows.sort(key=lambda row: row["id"])
        total = len(rows)
        return total, [row.copy() for row in rows if after_id is None or row["id"] > after_id][:limit]

    def get(self, country_id, *, for_update=False):
        row = self.rows.get(country_id)
        return row.copy() if row else None

    def code_exists(self, code, exclude_id=None):
        return any(row["codigo"] == code and row["estado_id"] != -1 and row["id"] != exclude_id
                   for row in self.rows.values())

    def create(self, values, actor_id):
        identifier = self.next_id
        self.next_id += 1
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        row = {"id": identifier, "idioma": "es-419", "estado_id": 1, "actualizado_en": now,
               "creado_en": now, "creado_por": actor_id, "actualizado_por": actor_id, **values}
        self.rows[identifier] = row
        return row.copy()

    def update(self, country_id, values, actor_id):
        row = self.rows[country_id]
        row.update(values)
        row["actualizado_por"] = actor_id
        row["actualizado_en"] += timedelta(microseconds=1)
        return row.copy()


class FakeAudit:
    def __init__(self): self.events = []
    def record(self, **event): self.events.append(event)


class FakeUow:
    def __init__(self):
        self.countries = FakeCountries()
        self.audit = FakeAudit()
        self.commits = 0
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def commit(self): self.commits += 1


def test_country_domain_normalizes_name_but_requires_official_uppercase_code():
    assert normalize({"nombre": "  Costa   Rica  ", "codigo": "CR"}) == {"nombre": "Costa Rica", "codigo": "CR"}
    with pytest.raises(InvalidCountry): normalize({"codigo": "cr"})
    with pytest.raises(InvalidCountry): normalize({"nombre": " \t "})


def test_create_edit_etag_and_audit():
    uow = FakeUow()
    cases = CountryUseCases(uow)
    created = cases.create({"nombre": "  Costa   Rica  ", "codigo": "CR"}, 3)
    assert created["nombre"] == "Costa Rica" and uow.commits == 1
    with pytest.raises(CountryProblem) as missing:
        cases.edit(created["id"], {"nombre": "Nuevo"}, None, 3)
    assert missing.value.kind is CountryProblemKind.PRECONDITION_REQUIRED
    with pytest.raises(CountryProblem) as stale:
        cases.edit(created["id"], {"nombre": "Nuevo"}, '"stale"', 3)
    assert stale.value.kind is CountryProblemKind.PRECONDITION_FAILED
    updated = cases.edit(created["id"], {"nombre": "Nuevo"}, version_tag(created), 3)
    assert updated["nombre"] == "Nuevo" and version_tag(updated) != version_tag(created)
    assert [event["action"] for event in uow.audit.events] == ["crear", "editar"]


def test_duplicate_code_restore_conflict_and_state():
    uow = FakeUow()
    cases = CountryUseCases(uow)
    first = cases.create({"nombre": "México", "codigo": "MX"}, 1)
    with pytest.raises(CountryProblem) as duplicate:
        cases.create({"nombre": "Otro", "codigo": "MX"}, 1)
    assert duplicate.value.kind is CountryProblemKind.CONFLICT
    cases.delete(first["id"], 1)
    assert cases.get(first["id"])["estado_id"] == -1
    replacement = cases.create({"nombre": "México nuevo", "codigo": "MX"}, 1)
    with pytest.raises(CountryProblem) as conflict:
        cases.restore(first["id"], 1)
    assert conflict.value.kind is CountryProblemKind.CONFLICT
    cases.delete(replacement["id"], 1)
    restored = cases.restore(first["id"], 1)
    assert restored["estado_id"] == 0
    assert cases.change_state(first["id"], 1, 1)["estado_id"] == 1


def test_list_cursor_is_bound_to_filters():
    cases = CountryUseCases(FakeUow())
    cases.create({"nombre": "México", "codigo": "MX"}, 1)
    cases.create({"nombre": "Colombia", "codigo": "CO"}, 1)
    first = cases.list("", "vigentes", None, None, 1)
    assert len(first["items"]) == 1 and first["siguiente"]
    second = cases.list("", "vigentes", None, first["siguiente"], 1)
    assert second["items"][0]["codigo"] == "CO"
    with pytest.raises(CountryProblem): cases.list("M", "vigentes", None, first["siguiente"], 1)
