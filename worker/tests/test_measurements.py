import pytest

from app.infrastructure.measurement_queue import (
    InvalidMeasurementPolicy,
    MeasurementQueue,
    measurement_waits,
    retry_delay_ms,
)
from app.infrastructure.measurement_worker_registry import PostgresMeasurementWorkerRegistry


def test_configured_measurement_retries_are_exact_and_exhaust():
    assert retry_delay_ms(1, 3, [30_000, 120_000]) == 30_000
    assert retry_delay_ms(2, 3, [30_000, 120_000]) == 120_000
    assert retry_delay_ms(3, 3, [30_000, 120_000]) is None


def test_measurement_retry_policy_fails_closed_when_missing_or_invalid():
    class Connection:
        def __init__(self, row): self.row = row
        def execute(self, *_args): return self
        def fetchone(self): return self.row

    with pytest.raises(InvalidMeasurementPolicy):
        MeasurementQueue._policy(Connection(None))
    with pytest.raises(InvalidMeasurementPolicy):
        MeasurementQueue._policy(Connection({
            "max_intentos": 3, "backoff_base_ms": 30_000, "backoff_max_ms": 29_999, "timeout_ms": 1,
        }))


def test_policy_is_loaded_per_operation_and_has_no_process_local_schedule():
    class Connection:
        query = ""
        params = None
        def execute(self, query, params):
            self.query, self.params = query, params
            return self
        def fetchone(self):
            return {"max_intentos": 3, "backoff_base_ms": 30_000,
                    "backoff_max_ms": 120_000, "timeout_ms": 60_000}

    conn = Connection()
    row = MeasurementQueue._policy(conn)
    assert measurement_waits(row) == (30_000, 120_000)
    assert "ops.politica_reintento" in conn.query
    assert conn.params == ("preparar_medicion",)


def test_measurement_policy_rejects_invalid_attempt_count_or_wait_order():
    with pytest.raises(InvalidMeasurementPolicy):
        measurement_waits({"max_intentos": 4, "backoff_base_ms": 30_000, "backoff_max_ms": 120_000})
    with pytest.raises(InvalidMeasurementPolicy):
        measurement_waits({"max_intentos": 3, "backoff_base_ms": 120_000, "backoff_max_ms": 30_000})
    assert measurement_waits({"max_intentos": 3, "backoff_base_ms": 10_000, "backoff_max_ms": 90_000}) == (10_000, 90_000)


def test_persisted_backoff_values_drive_attempt_waits_without_hardcoded_schedule():
    persisted = {"max_intentos": 3, "backoff_base_ms": 30_000, "backoff_max_ms": 120_000}
    waits = measurement_waits(persisted)
    assert retry_delay_ms(1, persisted["max_intentos"], waits) == 30_000
    assert retry_delay_ms(2, persisted["max_intentos"], waits) == 120_000
    assert retry_delay_ms(3, persisted["max_intentos"], waits) is None


def test_measurement_registry_uses_only_queue_scoped_database_functions():
    class Connection:
        def __init__(self): self.calls = []
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def execute(self, query, params): self.calls.append((query, params))

    class Settings:
        database_host = "localhost"
        database_port = 5432
        database_name = "discardable"
        database_user = "worker"
        database_passfile = ".passfile"

    conn = Connection()
    registry = PostgresMeasurementWorkerRegistry(Settings())
    registry._connect = lambda: conn
    worker_id = "host:123:q.mantenimiento:abc"
    registry.register(worker_id, "host", 123)
    registry.heartbeat(worker_id, 1)
    registry.unregister(worker_id)
    assert [call[0].split("(")[0] for call in conn.calls] == [
        "SELECT ops.fn_registrar_worker_mantenimiento",
        "SELECT ops.fn_latido_worker_mantenimiento",
        "SELECT ops.fn_borrar_worker_mantenimiento",
    ]
    assert all("ops.worker" not in query for query, _ in conn.calls)
