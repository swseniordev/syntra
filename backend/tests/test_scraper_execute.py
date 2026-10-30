"""Caso de uso de ejecución de Scrapers (enqueuer) sin PostgreSQL."""

import pytest

from app.modules.scrapers.application.service import (ScraperProblem, ScraperProblemKind, ScraperUseCases)


class FakeRuns:
    def __init__(self, scraper, reds, countries):
        self._scraper = scraper
        self._reds = reds
        self._countries = countries
        self.processes = {}
        self.tasks = []
        self.next_id = 100

    def list_for_measurement(self, medicion_id):
        return [dict(self._scraper)] if self._scraper and self._scraper["medicion_id"] == medicion_id else []

    def load(self, scraper_id):
        return dict(self._scraper) if self._scraper and self._scraper["id"] == scraper_id else None

    def active_reds(self, scraper_id):
        return [dict(red) for red in self._reds]

    def countries(self, scraper_id):
        return list(self._countries)

    def existing_process(self, idempotency):
        return self.processes.get(idempotency)

    def create_process(self, scraper, options, total, idempotency, actor_id):
        process_id = self.next_id
        self.next_id += 1
        self.processes[idempotency] = {"id": process_id, "estado": "en_cola"}
        self.last_options = options
        self.last_total = total
        return process_id

    def add_task(self, process_id, clave, tipo, objetivo):
        self.tasks.append((process_id, clave, tipo, objetivo))


class FakeAudit:
    def __init__(self): self.events = []
    def record(self, **event): self.events.append(event)


class FakeUow:
    def __init__(self, runs):
        self.runs = runs
        self.audit = FakeAudit()
        self.commits = 0
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def commit(self): self.commits += 1


def _scraper(**overrides):
    base = {"id": 1, "nombre": "Monitoreo", "medicion_id": 10, "cuenta_id": 2, "estado_id": 1,
            "gn_activo": False, "gn_registros": 50, "post_incorporar": False, "post_relevancia": True,
            "post_sentimiento": True, "post_clusters": False, "post_bots": False}
    base.update(overrides)
    return base


def test_creates_one_task_per_active_red_in_q_apify():
    runs = FakeRuns(_scraper(), [{"codigo": "x", "registros": 200}, {"codigo": "tiktok", "registros": 100}], [])
    cases = ScraperUseCases(FakeUow(runs))
    result = cases.execute(1, {}, "idem-key-abcdef123456", actor_id=9)
    assert result["estado"] == "en_cola" and result["reutilizado"] is False
    claves = {(clave, tipo, objetivo) for _, clave, tipo, objetivo in runs.tasks}
    assert claves == {("red:x", "apify", 200), ("red:tiktok", "apify", 100)}


def test_google_news_is_not_enqueued_yet():
    # Google News no tiene consumidor en q.apify: no se encola (dejaría el proceso colgado).
    # Con redes activas, el proceso se crea pero SOLO con tareas apify.
    runs = FakeRuns(_scraper(gn_activo=True), [{"codigo": "x", "registros": 50}], ["MX", "CO"])
    cases = ScraperUseCases(FakeUow(runs))
    cases.execute(1, {}, "idem-key-abcdef123456", actor_id=9)
    assert [tipo for _, _, tipo, _ in runs.tasks] == ["apify"]
    assert runs.last_total == 1  # el total del proceso no cuenta Google News


def test_only_google_news_is_rejected():
    # Sin redes activas y solo Google News: nada ejecutable, se rechaza sin crear proceso.
    runs = FakeRuns(_scraper(gn_activo=True), [], ["MX"])
    cases = ScraperUseCases(FakeUow(runs))
    with pytest.raises(ScraperProblem) as problem:
        cases.execute(1, {}, "idem-key-abcdef123456", actor_id=9)
    assert problem.value.kind == ScraperProblemKind.VALIDATION
    assert runs.tasks == []


def test_idempotent_replay_returns_existing_process():
    runs = FakeRuns(_scraper(), [{"codigo": "x", "registros": 50}], [])
    uow = FakeUow(runs)
    cases = ScraperUseCases(uow)
    first = cases.execute(1, {}, "idem-key-abcdef123456", actor_id=9)
    second = cases.execute(1, {}, "idem-key-abcdef123456", actor_id=9)
    assert first["proceso_id"] == second["proceso_id"]
    assert second["reutilizado"] is True
    assert len(runs.tasks) == 1  # no se duplicaron tareas


def test_list_returns_scrapers_of_the_measurement():
    runs = FakeRuns(_scraper(), [{"codigo": "x", "registros": 50}], [])
    cases = ScraperUseCases(FakeUow(runs))
    assert cases.list(10)["items"][0]["id"] == 1
    assert cases.list(999)["items"] == []


def test_rejects_short_idempotency_key():
    runs = FakeRuns(_scraper(), [{"codigo": "x", "registros": 50}], [])
    cases = ScraperUseCases(FakeUow(runs))
    with pytest.raises(ScraperProblem) as problem:
        cases.execute(1, {}, "corta", actor_id=9)
    assert problem.value.kind == ScraperProblemKind.VALIDATION


def test_rejects_scraper_without_sources():
    runs = FakeRuns(_scraper(gn_activo=False), [], [])
    cases = ScraperUseCases(FakeUow(runs))
    with pytest.raises(ScraperProblem) as problem:
        cases.execute(1, {}, "idem-key-abcdef123456", actor_id=9)
    assert problem.value.kind == ScraperProblemKind.VALIDATION


def test_inactive_scraper_conflicts():
    runs = FakeRuns(_scraper(estado_id=0), [{"codigo": "x", "registros": 50}], [])
    cases = ScraperUseCases(FakeUow(runs))
    with pytest.raises(ScraperProblem) as problem:
        cases.execute(1, {}, "idem-key-abcdef123456", actor_id=9)
    assert problem.value.kind == ScraperProblemKind.CONFLICT


def test_overrides_effective_options_from_body():
    runs = FakeRuns(_scraper(post_incorporar=False), [{"codigo": "x", "registros": 50}], [])
    cases = ScraperUseCases(FakeUow(runs))
    cases.execute(1, {"al_incorporar": {"incorporar": True}}, "idem-key-abcdef123456", actor_id=9)
    assert runs.last_options["al_incorporar"]["incorporar"] is True
    assert runs.last_options["al_incorporar"]["relevancia"] is True  # viene del scraper


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
