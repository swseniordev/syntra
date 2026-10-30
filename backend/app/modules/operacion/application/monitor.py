"""Consulta de estado de las colas aprobadas y procesos propios."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


MONITORED_QUEUES = ("q.notificaciones", "q.reportes", "q.ingesta")
MONITORED_PROCESS_TYPES = ("correo_acceso", "exportacion", "preparar_medicion", "carga_scraper")
SAFE_TASK_ERRORS = {
    "correo_proveedor_fallido": "El proveedor de correo rechazó o no confirmó la entrega.",
    "exportacion_fallida": "No fue posible generar la exportación.",
    "worker_interrumpido": "El worker interrumpió la tarea y podrá reintentarse según la política vigente.",
    "payload_invalido": "La tarea no contiene los datos requeridos.",
    "usuario_no_elegible": "El usuario ya no cumple las condiciones para recibir el correo.",
    "preparacion_fallida": "No fue posible preparar la estructura de la medición.",
}


class OperationsReader(Protocol):
    def queues(self) -> list[dict[str, Any]]: ...
    def workers(self) -> list[dict[str, Any]]: ...
    def processes(self, owner_id: int, filters: dict[str, Any], after: tuple[datetime, int] | None,
                  limit: int, visible_types: tuple[str, ...]) -> list[dict[str, Any]]: ...
    def process_statistics(self, owner_id: int, visible_types: tuple[str, ...]) -> dict[str, Any]: ...
    def process(self, process_id: int) -> dict[str, Any] | None: ...
    def measurement_process_visible(self, process_id: int, owner_id: int, global_access: bool) -> bool: ...
    def tasks(self, process_id: int) -> list[dict[str, Any]]: ...


class OperationsMonitor:
    def __init__(self, reader: OperationsReader):
        self.reader = reader

    def queues(self) -> list[dict[str, Any]]:
        return self.reader.queues()

    def workers(self) -> list[dict[str, Any]]:
        return self.reader.workers()

    def processes(self, owner_id: int, filters: dict[str, Any], after: tuple[datetime, int] | None,
                  limit: int, visible_types: tuple[str, ...]) -> list[dict[str, Any]]:
        allowed_types = tuple(kind for kind in MONITORED_PROCESS_TYPES if kind in visible_types)
        if filters.get("tipo") not in (None, *allowed_types) or not allowed_types:
            return []
        return self.reader.processes(owner_id, filters, after, limit + 1, allowed_types)

    def process_statistics(self, owner_id: int, visible_types: tuple[str, ...]) -> dict[str, Any]:
        allowed_types = tuple(kind for kind in MONITORED_PROCESS_TYPES if kind in visible_types)
        if not allowed_types:
            return {
                "en_ejecucion_o_en_cola": 0, "completados_24h": 0,
                "registros_procesados_24h": 0, "errores_advertencias_7d": 0,
                "duracion_promedio_ms": None, "duracion_maxima_ms": None,
                "sla_cumplimiento_pct": None, "ultimas_duraciones": [],
            }
        return self.reader.process_statistics(owner_id, allowed_types)

    def process_detail(self, process_id: int, owner_id: int,
                       visible_types: tuple[str, ...] = MONITORED_PROCESS_TYPES,
                       global_access: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        row = self.reader.process(process_id)
        if row is None or row["creado_por"] != owner_id:
            return None
        kind = row["opciones"].get("kind") if row["opciones"] else None
        if row["tipo"] not in MONITORED_PROCESS_TYPES or row["tipo"] not in visible_types:
            return None
        if row["tipo"] == "exportacion" and kind != "auditoria":
            return None
        if row["tipo"] == "preparar_medicion" and (
            kind != "preparacion_medicion" or
            not self.reader.measurement_process_visible(process_id, owner_id, global_access)
        ):
            return None
        if row["tipo"] == "carga_scraper" and not self.reader.measurement_process_visible(
            process_id, owner_id, global_access
        ):
            return None
        # La salida nunca incluye opciones ni payloads, que pueden contener filtros/datos personales.
        safe = {"id": row["id"], "tipo": row["tipo"]}
        tasks = [{key: task.get(key) for key in (
            "id", "clave", "tipo", "estado", "intentos", "objetivo", "ok", "errores",
            "iniciado_en", "finalizado_en",
        )} | {
            "error_codigo": task.get("error_codigo") if task.get("error_codigo") in SAFE_TASK_ERRORS else (
                "error_no_clasificado" if task.get("error_codigo") else None),
            "error_mensaje": SAFE_TASK_ERRORS.get(task.get("error_codigo"), "Error de tarea registrado; detalle no disponible."),
        } for task in self.reader.tasks(process_id)]
        return safe, tasks
