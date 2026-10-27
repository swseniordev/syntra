from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routers.mediciones import MedicionIn, crear_medicion
from app.core.identity import Principal
from app.modules.mediciones.application.service import MeasurementProblem, MeasurementUseCases
from app.modules.mediciones.domain.rules import InvalidMeasurement, retry_delay_ms, validate_creation
from app.modules.mediciones.infrastructure.postgres import PostgresMeasurementRepository


def _request(**extra):
    return {
        "cuenta_id": 3,
        "nombre": "Medición de aceptación",
        "fuentes": [{"origen": "manual", "activo": True}],
        **extra,
    }


def test_measurement_contract_rejects_unknown_fields_and_bad_prompt_versions():
    with pytest.raises(ValidationError):
        MedicionIn.model_validate({**_request(), "estado_tecnico": "en_cola"})
    with pytest.raises(ValidationError):
        MedicionIn.model_validate({**_request(), "prompts": [{
            "tipo": "cluster", "origen": "defecto", "version": 0,
        }]})
    with pytest.raises(ValidationError):
        MedicionIn.model_validate({**_request(), "fuentes": [{"origen": "manual", "al_cargar": {"inventado": True}}]})


def test_creation_requires_a_real_source_or_scraper_and_allows_scraper_only():
    with pytest.raises(InvalidMeasurement):
        validate_creation({"cuenta_id": 1, "nombre": "M", "fuentes": [], "scrapers": []})
    validate_creation({
        "cuenta_id": 1, "nombre": "M", "fuentes": [],
        "scrapers": [{"nombre": "Scraper", "inicio": datetime(2026, 1, 1, tzinfo=timezone.utc),
                       "fin": datetime(2026, 1, 2, tzinfo=timezone.utc)}],
    })


@pytest.mark.parametrize("start,end", [
    (datetime(2026, 1, 1), datetime(2026, 1, 2)),
    (datetime(2026, 1, 2, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
])
def test_scraper_requires_ordered_timezone_aware_dates(start, end):
    with pytest.raises(InvalidMeasurement):
        validate_creation({"cuenta_id": 1, "nombre": "M", "fuentes": [],
                           "scrapers": [{"nombre": "S", "inicio": start, "fin": end}]})


def test_meltwater_schedule_requires_valid_window_and_frequency():
    valid = {"cuenta_id": 1, "nombre": "M", "fuentes": [{"origen": "meltwater", "config": {"busqueda_id": "MW-42"}}],
             "programacion_meltwater": {"activa": True,
                 "inicio": "2026-01-01T00:00:00Z", "fin": "2026-01-02T00:00:00Z", "frecuencia_min": 15}}
    validate_creation(valid)
    with pytest.raises(InvalidMeasurement):
        validate_creation({**valid, "programacion_meltwater": {**valid["programacion_meltwater"], "frecuencia_min": 14}})
    with pytest.raises(InvalidMeasurement):
        validate_creation({**valid, "programacion_meltwater": {**valid["programacion_meltwater"],
                                                                  "fin": "2025-12-31T23:59:00Z"}})


def test_measurement_list_query_pushes_contract_filters_and_stable_cursor_to_postgres():
    class Connection:
        query = ""
        params = ()
        def execute(self, query, params):
            self.query, self.params = query, params
            return self
        def fetchall(self): return []

    conn = Connection()
    filters = {"q": "agua", "estado_id": -99, "cuenta_id": 4, "cliente_id": 2,
               "coyuntura": True, "fuente": "googlenews"}
    rows = PostgresMeasurementRepository(conn).list(11, False, 26,
        ("2026-01-01T00:00:00+00:00", 9), filters)
    assert rows == []
    assert len(conn.params) == 21
    assert "ORDER BY m.creado_en,m.id LIMIT %s" in conn.query
    assert "c.cliente_id=%s" in conn.query and "s.gn_activo" in conn.query
    assert conn.params[-4:] == ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", 9, 26)


def test_measurement_retry_schedule_is_exact_and_terminal_after_attempt_three():
    assert retry_delay_ms(1, 3, [30_000, 120_000]) == 30_000
    assert retry_delay_ms(2, 3, [30_000, 120_000]) == 120_000
    assert retry_delay_ms(3, 3, [30_000, 120_000]) is None
    with pytest.raises(InvalidMeasurement):
        retry_delay_ms(1, 3, [30_000])


class _UseCaseUow:
    def __init__(self, fail_audit=False):
        self.committed = False
        self.rolled_back = False
        self.fail_audit = fail_audit
        self.measurements = self
        self.audit = self
        self.current = {"id": 41, "nombre": "Medición", "actualizado_en": datetime(2026, 1, 1, tzinfo=timezone.utc),
                        "fuentes": [{"origen": "manual", "activo": True, "config": {}, "al_cargar": {}}],
                        "programacion_meltwater": {"activa": False}}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None or not self.committed:
            self.rolled_back = True

    def create(self, values, actor_id, global_access):
        assert actor_id == 9
        return {"id": 41, "nombre": values["nombre"], "proceso_preparacion_id": 72}

    def record(self, **_kwargs):
        if self.fail_audit:
            raise RuntimeError("audit unavailable")

    def commit(self):
        self.committed = True

    def get_for_update(self, *_args):
        return self.current

    def get(self, _measurement_id, actor_id, _global_access):
        return self.current if actor_id == 9 else None

    def source_summary(self, _measurement_id):
        return [{"origen": "archivo", "cargados": 4, "duplicados": 2,
                 "por_fiscalizar": 1}]

    def update_configuration(self, _measurement_id, changes, _actor_id):
        self.current = {**self.current, **changes, "actualizado_en": datetime(2026, 1, 2, tzinfo=timezone.utc)}
        return self.current


def test_measurement_configuration_audit_and_durable_process_share_one_unit_of_work():
    uow = _UseCaseUow()
    created = MeasurementUseCases(uow).create(_request(), 9, False)
    assert created["id"] == 41
    assert created["proceso_preparacion_id"] == 72
    assert uow.committed and not uow.rolled_back


def test_measurement_audit_failure_rolls_back_the_unit_of_work():
    uow = _UseCaseUow(fail_audit=True)
    with pytest.raises(RuntimeError):
        MeasurementUseCases(uow).create(_request(), 9, False)
    assert not uow.committed and uow.rolled_back


def test_summary_requires_visible_measurement_and_aggregates_persisted_sources():
    cases = MeasurementUseCases(_UseCaseUow())
    result = cases.summary(41, 9, False)
    assert result["por_fuente"][0]["origen"] == "archivo"
    assert result["pipeline"]["cargados"] == 4
    assert result["pipeline"]["duplicados"] == 2
    with pytest.raises(MeasurementProblem) as denied:
        cases.summary(41, 12, False)
    assert denied.value.status == 404


def test_measurement_create_endpoint_requires_permission_and_sets_location():
    principal = Principal(
        user={"id": 9}, role={"ver_todas": False}, permissions=frozenset({"mediciones:crear"}),
        session_id=uuid4(),
    )
    class Cases:
        def create(self, *_args): return {"id": 41, "proceso_preparacion_id": 72}

    from fastapi import Response
    response = Response()
    result = crear_medicion(MedicionIn.model_validate(_request()), response, principal, Cases())
    assert result["proceso_preparacion_id"] == 72
    assert response.headers["Location"] == "/api/v1/mediciones/41"

    denied = Principal(user={"id": 9}, role={"ver_todas": False}, permissions=frozenset(), session_id=uuid4())
    from app.core.identity import require
    with pytest.raises(HTTPException) as exc:
        require("mediciones:crear")(denied)
    assert exc.value.status_code == 403


def test_measurement_patch_requires_etag_rejects_stale_version_and_audits_atomic_update():
    from app.modules.mediciones.application.versioning import version_tag
    uow = _UseCaseUow()
    cases = MeasurementUseCases(uow)
    previous_tag = version_tag(uow.current)
    result = cases.edit(41, {"auto_publicar": True}, previous_tag, 9, True)
    assert result["auto_publicar"] is True
    assert uow.committed and not uow.rolled_back

    with pytest.raises(MeasurementProblem) as missing:
        cases.edit(41, {"auto_publicar": False}, None, 9, True)
    assert missing.value.status == 428
    with pytest.raises(MeasurementProblem) as stale:
        cases.edit(41, {"auto_publicar": False}, previous_tag, 9, True)
    assert stale.value.status == 412


def test_step2_validation_requires_meltwater_search_id_and_active_source_for_schedule():
    from app.modules.mediciones.application.service import MeasurementUseCases
    before = {"fuentes": [], "programacion_meltwater": {"activa": False}}
    with pytest.raises(MeasurementProblem) as missing_id:
        MeasurementUseCases._validate_step2({"fuentes": [{"origen": "meltwater", "activo": True, "config": {}}],
                                               "programacion_meltwater": {"activa": True,
                                                   "inicio": "2026-01-01T00:00:00Z", "fin": "2026-01-02T00:00:00Z", "frecuencia_min": 30}}, before)
    assert missing_id.value.status == 400
