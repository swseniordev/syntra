"""Reglas de Prompts con dobles de persistencia y auditoría."""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.prompts.application.service import PromptProblem, PromptProblemKind, PromptUseCases, version_tag
from app.modules.prompts.domain.rules import InvalidPrompt, normalize


class FakePrompts:
    def __init__(self):
        self.rows = {}
        self.history = {}
        self.next_id = 1
        self.scopes = []

    def list(self, query, state, kind, network, after_id, limit):
        rows = [row for row in self.rows.values() if
                (state == "vigentes" and row["estado_id"] != -1 or state == "activos" and row["estado_id"] == 1
                 or state == "inactivos" and row["estado_id"] == 0 or state == "eliminados" and row["estado_id"] == -1)
                and query.lower() in (row["nombre"] + row["contenido"]).lower()
                and (kind is None or row["tipo"] == kind)
                and (network is None or row["red"] == (None if network == "_" else network))]
        rows.sort(key=lambda row: row["id"])
        return len(rows), [row.copy() for row in rows if after_id is None or row["id"] > after_id][:limit]

    def get(self, prompt_id, *, for_update=False):
        row = self.rows.get(prompt_id)
        return row.copy() if row else None

    def lock_default_scope(self, kind, network):
        self.scopes.append((kind, network))

    def demote_default(self, kind, network, exclude_id, actor_id):
        result = []
        for row in list(self.rows.values()):
            if row["tipo"] == kind and row["red"] == network and row["por_defecto"] and row["estado_id"] == 1 and row["id"] != exclude_id:
                before = row.copy()
                after = self.update(row["id"], {"por_defecto": False}, actor_id)
                result.append((before, after))
        return result

    def create(self, values, actor_id):
        identifier = self.next_id
        self.next_id += 1
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        row = {"id": identifier, "red": None, "por_defecto": False, "estado_id": 1, "version_actual": 1,
               "creado_en": now, "creado_por": actor_id, "actualizado_en": now, "actualizado_por": actor_id, **values}
        self.rows[identifier] = row
        self.history[identifier] = [{"version": 1, "contenido": row["contenido"]}]
        return row.copy()

    def update(self, prompt_id, values, actor_id):
        row = self.rows[prompt_id]
        if "contenido" in values and values["contenido"] != row["contenido"]:
            row["version_actual"] += 1
            self.history[prompt_id].append({"version": row["version_actual"], "contenido": values["contenido"]})
        row.update(values)
        row["actualizado_en"] += timedelta(microseconds=1)
        row["actualizado_por"] = actor_id
        return row.copy()

    def versions(self, prompt_id):
        return list(reversed(self.history[prompt_id]))


class FakeAudit:
    def __init__(self): self.events = []
    def record(self, **event): self.events.append(event)


class FakeUow:
    def __init__(self):
        self.prompts = FakePrompts()
        self.audit = FakeAudit()
        self.commits = 0
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def commit(self): self.commits += 1


def payload(**changes):
    return {"tipo": "cluster", "red": None, "nombre": "Clusters", "contenido": "Agrupa registros por temas políticos.",
            "por_defecto": False, "estado_id": 1, **changes}


def test_domain_rejects_short_content_and_network_on_cluster():
    with pytest.raises(InvalidPrompt): normalize(payload(contenido="corto"))
    with pytest.raises(InvalidPrompt): normalize(payload(red="x"))
    with pytest.raises(InvalidPrompt): normalize(payload(por_defecto=True, estado_id=0))


def test_default_replacement_and_version_history():
    uow = FakeUow()
    cases = PromptUseCases(uow)
    first = cases.create(payload(por_defecto=True), 1)
    second = cases.create(payload(nombre="Otro", contenido="Otro contenido suficientemente largo.", por_defecto=True), 1)
    assert cases.get(first["id"])["por_defecto"] is False
    assert cases.get(second["id"])["por_defecto"] is True
    assert [event["action"] for event in uow.audit.events] == ["crear", "editar", "crear"]
    changed = cases.edit(second["id"], {"contenido": "Contenido nuevo suficientemente largo."}, version_tag(second), 1)
    assert changed["version_actual"] == 2
    assert cases.versions(second["id"])[0]["contenido"] == "Contenido nuevo suficientemente largo."
    assert cases.versions(second["id"])[1]["contenido"] == second["contenido"]
    metadata = cases.edit(second["id"], {"nombre": "Otro nombre"}, version_tag(changed), 1)
    assert metadata["version_actual"] == 2
    assert len(cases.versions(second["id"])) == 2


def test_precondition_and_inactive_default_behavior():
    uow = FakeUow()
    cases = PromptUseCases(uow)
    row = cases.create(payload(por_defecto=True), 1)
    with pytest.raises(PromptProblem) as missing:
        cases.edit(row["id"], {"nombre": "Nuevo"}, None, 1)
    assert missing.value.kind is PromptProblemKind.PRECONDITION_REQUIRED
    with pytest.raises(PromptProblem) as stale:
        cases.edit(row["id"], {"nombre": "Nuevo"}, '"stale"', 1)
    assert stale.value.kind is PromptProblemKind.PRECONDITION_FAILED
    inactive = cases.change_state(row["id"], 0, 1)
    assert inactive["estado_id"] == 0 and inactive["por_defecto"] is False
    cases.delete(row["id"], 1)
    assert cases.restore(row["id"], 1)["estado_id"] == 0
