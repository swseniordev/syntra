from uuid import uuid4

from fastapi import HTTPException, Response

from app.api.routers.ops import colas, workers
from app.api.routers.procesos import _decode_cursor, estadisticas, listar, tareas
from app.core.identity import Principal, require
from app.main import app
from app.modules.operacion.application.monitor import OperationsMonitor
import pytest


class FakeReader:
    def __init__(self):
        self.process_filters = None

    def queues(self):
        return [{"cola": "q.notificaciones", "en_cola": 1, "en_ejecucion": 0,
                 "con_error": 2, "mas_antigua_s": 12, "workers": 0},
                {"cola": "q.reportes", "en_cola": 0, "en_ejecucion": 1,
                 "con_error": 0, "mas_antigua_s": 0, "workers": 1}]

    def workers(self):
        return [{"id": "test:123:q.reportes:abc", "servidor": "test", "colas": ["q.reportes"],
                 "iniciado_en": "2026-10-22T10:00:00Z", "latido": "2026-10-22T10:01:00Z",
                 "tareas_en_curso": 1, "vivo": False}]

    def processes(self, owner_id, filters, after, limit, visible_types):
        self.process_filters = (owner_id, filters, after, limit, visible_types)
        return [{"id": 4, "tipo": "exportacion", "estado": "error"}]

    def process_statistics(self, owner_id, visible_types):
        self.statistics_filters = (owner_id, visible_types)
        return {"en_ejecucion_o_en_cola": 1, "completados_24h": 2,
                "registros_procesados_24h": 3, "errores_advertencias_7d": 4,
                "duracion_promedio_ms": 250, "duracion_maxima_ms": 500,
                "sla_cumplimiento_pct": 100.0, "ultimas_duraciones": []}

    def process(self, process_id):
        return {"id": process_id, "tipo": "exportacion", "estado": "error", "creado_por": 7,
                "opciones": {"kind": "auditoria", "filters": {"email": "persona@example.com"}},
                "errores": 1, "detalle": "No debe salir", "duracion_ms": 25}

    def tasks(self, process_id):
        return [{"id": 9, "clave": "auditoria", "tipo": "auditoria_exportar", "estado": "error",
                 "intentos": 3, "ok": 0, "errores": 1, "error_codigo": "correo_proveedor_fallido",
                 "error_mensaje": "SMTP secret=private-token", "iniciado_en": None, "finalizado_en": None,
                 "payload": {"secret": "private-token"}}]


def _principal(permissions):
    return Principal(user={"id": 7}, role={"id": 1, "ver_todas": True},
                     permissions=frozenset(permissions), session_id=uuid4())


def test_ops_contract_and_permissions():
    reader = FakeReader()
    monitor = OperationsMonitor(reader)
    principal = _principal({"procesos:ver", "auditoria:ver"})
    assert colas(principal, monitor)[0]["cola"] == "q.notificaciones"
    assert workers(principal, monitor)[0]["vivo"] is False
    response = Response()
    assert listar(response, tipo="exportacion", limite=1, principal=principal, monitor=monitor)[0]["id"] == 4
    assert reader.process_filters[0] == 7
    assert reader.process_filters[4] == ("exportacion",)
    stats = estadisticas(principal, monitor)
    assert stats["completados_24h"] == 2
    assert reader.statistics_filters == (7, ("exportacion",))
    spec = app.openapi()
    assert spec["paths"]["/api/v1/ops/colas"]["get"].get("security")
    assert spec["paths"]["/api/v1/ops/workers"]["get"].get("security")

    unprivileged = _principal(set())
    with pytest.raises(HTTPException) as denied:
        require("procesos:ver")(unprivileged)
    assert denied.value.status_code == 403


def test_process_statistics_returns_empty_without_visible_module_permissions():
    reader = FakeReader()
    result = OperationsMonitor(reader).process_statistics(7, ())
    assert result["en_ejecucion_o_en_cola"] == 0
    assert result["duracion_promedio_ms"] is None
    assert result["ultimas_duraciones"] == []
    assert not hasattr(reader, "statistics_filters")


def test_process_task_detail_is_owner_and_module_scoped_and_redacted():
    reader = FakeReader()
    monitor = OperationsMonitor(reader)
    result = tareas(4, _principal({"procesos:ver", "auditoria:ver"}), monitor)[0]
    assert result["error_codigo"] == "correo_proveedor_fallido"
    assert result["error_mensaje"] == "El proveedor de correo rechazó o no confirmó la entrega."
    assert "payload" not in result
    assert "SMTP secret=private-token" not in str(result)
    try:
        tareas(4, _principal({"procesos:ver"}), monitor)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Se esperaba denegación de auditoria:ver")


def test_process_detail_hides_private_options_and_foreign_processes():
    monitor = OperationsMonitor(FakeReader())
    detail = monitor.process_detail(4, 7)
    assert detail is not None
    process, tasks = detail
    assert "opciones" not in process
    assert "persona@example.com" not in str(process)
    assert "SMTP secret=private-token" not in str(tasks)
    assert monitor.process_detail(4, 8) is None


def test_process_cursor_requires_timezone_and_stable_id():
    import base64
    import json

    encoded = base64.urlsafe_b64encode(json.dumps({
        "creado_en": "2026-10-22T10:00:00+00:00", "id": 42,
    }).encode()).decode().rstrip("=")
    assert _decode_cursor(encoded) == (__import__("datetime").datetime.fromisoformat("2026-10-22T10:00:00+00:00"), 42)
    with pytest.raises(HTTPException) as invalid:
        _decode_cursor(base64.urlsafe_b64encode(b'{"creado_en":"2026-10-22T10:00:00","id":42}').decode().rstrip("="))
    assert invalid.value.status_code == 400


def test_process_reader_filters_recent_creation_and_orders_stably():
    from app.modules.operacion.infrastructure.postgres import PostgresOperationsReader

    class FakeConnection:
        def __init__(self):
            self.query = ""
            self.params = ()

        def execute(self, query, params):
            self.query, self.params = query, params
            return self

        def fetchall(self):
            return []

    connection = FakeConnection()
    reader = PostgresOperationsReader(connection)
    from datetime import datetime, timezone
    cursor_time = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)
    reader.processes(7, {}, (cursor_time, 42), 11, ("correo_acceso", "exportacion"))
    assert "creado_en >= now()-interval '7 days'" in connection.query
    assert "ORDER BY creado_en DESC,id DESC" in connection.query
    assert "(creado_en,id) < (%s,%s)" in connection.query
    assert tuple(connection.params[-3:-1]) == (cursor_time, 42)
    assert connection.params[-1] == 11
