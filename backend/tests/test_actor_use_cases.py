"""Reglas y casos de uso de Actores sin conexión PostgreSQL."""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.actores.application.service import (ActorProblem, ActorProblemKind, ActorUseCases, version_tag)
from app.modules.actores.domain.rules import InvalidActor, normalize


class FakeActors:
    def __init__(self):
        self.rows = {}
        self.next_id = 1

    def list(self, query, state, after_id, limit):
        rows = [row for row in self.rows.values() if
                (state == "vigentes" and row["estado_id"] != -1 or state == "activos" and row["estado_id"] == 1
                 or state == "inactivos" and row["estado_id"] == 0 or state == "eliminados" and row["estado_id"] == -1)
                and query.lower() in (row["nombre"] + row["actor"]).lower()]
        rows.sort(key=lambda row: row["id"])
        return len(rows), [row.copy() for row in rows if after_id is None or row["id"] > after_id][:limit]

    def get(self, actor_id, *, for_update=False):
        row = self.rows.get(actor_id)
        return row.copy() if row else None

    def create(self, values, actor_id):
        identifier = self.next_id
        self.next_id += 1
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        row = {"id": identifier, "uso": "busqueda", "estado_id": 1, "max_registros": 1000,
               "max_urls_por_corrida": 1000, "memoria_mb": 4096, "nota": None, "actualizado_en": now,
               "creado_en": now, "creado_por": actor_id, "actualizado_por": actor_id, **values}
        self.rows[identifier] = row
        return row.copy()

    def update(self, actor_id, values, user_id):
        row = self.rows[actor_id]
        row.update(values)
        row["actualizado_por"] = user_id
        row["actualizado_en"] += timedelta(microseconds=1)
        return row.copy()


class FakeAudit:
    def __init__(self): self.events = []
    def record(self, **event): self.events.append(event)


class FakeUow:
    def __init__(self):
        self.actors = FakeActors()
        self.audit = FakeAudit()
        self.commits = 0
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def commit(self): self.commits += 1


def test_domain_normalizes_name_and_validates_actor_and_red():
    assert normalize({"nombre": "  X   búsqueda ", "actor": " apidojo/tweet-scraper ", "red": "X"}) == \
        {"nombre": "X búsqueda", "actor": "apidojo/tweet-scraper", "red": "x"}
    with pytest.raises(InvalidActor): normalize({"actor": "sin-barra"})
    with pytest.raises(InvalidActor): normalize({"red": "linkedin"})
    with pytest.raises(InvalidActor): normalize({"max_registros": 0})


def test_create_records_audit_and_commits():
    uow = FakeUow()
    cases = ActorUseCases(uow)
    row = cases.create({"red": "x", "nombre": "X búsqueda", "actor": "apidojo/tweet-scraper"}, actor_id=7)
    assert row["red"] == "x" and row["id"] == 1
    assert uow.commits == 1
    assert uow.audit.events[0]["action"] == "crear"
    assert uow.audit.events[0]["entity_type"] == "Actor"


def test_edit_requires_if_match_and_detects_stale_version():
    uow = FakeUow()
    cases = ActorUseCases(uow)
    row = cases.create({"red": "x", "nombre": "A", "actor": "a/b"}, actor_id=1)
    with pytest.raises(ActorProblem) as missing:
        cases.edit(row["id"], {"nombre": "B"}, None, user_id=1)
    assert missing.value.kind == ActorProblemKind.PRECONDITION_REQUIRED
    with pytest.raises(ActorProblem) as stale:
        cases.edit(row["id"], {"nombre": "B"}, '"otra"', user_id=1)
    assert stale.value.kind == ActorProblemKind.PRECONDITION_FAILED
    updated = cases.edit(row["id"], {"nombre": "B"}, version_tag(row), user_id=1)
    assert updated["nombre"] == "B"


def test_delete_then_restore_moves_through_states():
    uow = FakeUow()
    cases = ActorUseCases(uow)
    row = cases.create({"red": "tiktok", "nombre": "T", "actor": "clockworks/tiktok-scraper"}, actor_id=1)
    cases.delete(row["id"], user_id=1)
    assert uow.actors.get(row["id"])["estado_id"] == -1
    restored = cases.restore(row["id"], user_id=1)
    assert restored["estado_id"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
