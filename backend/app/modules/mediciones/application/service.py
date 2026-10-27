"""Casos de uso de creación y consulta de Mediciones."""

from __future__ import annotations

from typing import Any

import psycopg

from app.modules.mediciones.application.ports import MeasurementUnitOfWork
from app.modules.mediciones.domain.rules import InvalidMeasurement, validate_creation
from app.modules.mediciones.application.versioning import version_tag


class MeasurementProblem(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class MeasurementUseCases:
    def __init__(self, uow: MeasurementUnitOfWork):
        self.uow = uow

    def create(self, values: dict[str, Any], actor_id: int, global_access: bool) -> dict[str, Any]:
        try:
            validate_creation(values)
        except InvalidMeasurement as exc:
            raise MeasurementProblem(400, str(exc)) from exc
        try:
            with self.uow:
                row = self.uow.measurements.create(values, actor_id, global_access)
                self.uow.audit.record(actor_id=actor_id, module="mediciones", action="creacion",
                                      entity_type="Medición", entity_id=str(row["id"]),
                                      entity_name=row["nombre"], after=row)
                self.uow.commit()
                return row
        except MeasurementProblem:
            raise
        except PermissionError as exc:
            raise MeasurementProblem(403, str(exc)) from exc
        except LookupError as exc:
            raise MeasurementProblem(400, str(exc)) from exc
        except psycopg.errors.UniqueViolation as exc:
            raise MeasurementProblem(409, "La solicitud entra en conflicto con un registro existente") from exc
        except psycopg.errors.ForeignKeyViolation as exc:
            raise MeasurementProblem(400, "Una referencia seleccionada ya no está disponible") from exc
        except psycopg.errors.CheckViolation as exc:
            raise MeasurementProblem(400, "La configuración de la medición no cumple las reglas vigentes") from exc

    def list(self, actor_id: int, global_access: bool, limit: int,
             after: tuple[str, int] | None = None,
             filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.uow.measurements.list(actor_id, global_access, limit, after, filters or {})

    def get(self, measurement_id: int, actor_id: int, global_access: bool) -> dict[str, Any]:
        result = self.uow.measurements.get(measurement_id, actor_id, global_access)
        if result is None:
            raise MeasurementProblem(404, "Medición no encontrada")
        return result

    def summary(self, measurement_id: int, actor_id: int, global_access: bool) -> dict[str, Any]:
        # La consulta de agregados solo se ejecuta tras verificar la visibilidad
        # de la medición y su cuenta para este usuario.
        self.get(measurement_id, actor_id, global_access)
        sources = self.uow.measurements.source_summary(measurement_id)
        fields = ("cargados", "duplicados", "por_fiscalizar", "cumplen_sin_incorporar",
                  "descartados", "incorporados", "con_metricas", "transcritos",
                  "analizados", "en_tablero", "eliminados", "con_error")
        return {"pipeline": {field: sum(int(row.get(field) or 0) for row in sources)
                              for field in fields}, "por_fuente": sources}

    def edit(self, measurement_id: int, changes: dict[str, Any], expected_version: str | None,
             actor_id: int, global_access: bool) -> dict[str, Any]:
        if expected_version is None:
            raise MeasurementProblem(428, "Se requiere If-Match")
        try:
            with self.uow:
                previous = self.uow.measurements.get_for_update(measurement_id, actor_id, global_access)
                if previous is None:
                    raise MeasurementProblem(404, "Medición no encontrada")
                if expected_version != version_tag(previous):
                    raise MeasurementProblem(412, "La medición cambió desde la última lectura")
                if not changes:
                    return previous
                if "fuentes" in changes or "programacion_meltwater" in changes:
                    self._validate_step2(changes, previous)
                row = self.uow.measurements.update_configuration(measurement_id, changes, actor_id)
                self.uow.audit.record(actor_id=actor_id, module="mediciones", action="edicion",
                                      entity_type="Medición", entity_id=str(measurement_id),
                                      entity_name=row["nombre"], before=previous, after=row)
                self.uow.commit()
                return row
        except MeasurementProblem:
            raise
        except PermissionError as exc:
            raise MeasurementProblem(403, str(exc)) from exc
        except LookupError as exc:
            raise MeasurementProblem(400, str(exc)) from exc
        except psycopg.errors.ForeignKeyViolation as exc:
            raise MeasurementProblem(400, "Una fuente seleccionada ya no está disponible") from exc
        except psycopg.errors.CheckViolation as exc:
            raise MeasurementProblem(400, "La configuración de la medición no cumple las reglas vigentes") from exc

    @staticmethod
    def _validate_step2(changes: dict[str, Any], previous: dict[str, Any]) -> None:
        sources = changes.get("fuentes", previous.get("fuentes", []))
        active = {item["origen"] for item in sources if item.get("activo", True)}
        schedule = changes.get("programacion_meltwater", previous.get("programacion_meltwater", {})) or {}
        meltwater = next((item for item in sources if item["origen"] == "meltwater"), None)
        search_id = ((meltwater or {}).get("config") or {}).get("busqueda_id", "").strip()
        if meltwater and meltwater.get("activo", True) and not search_id:
            raise MeasurementProblem(400, "Meltwater requiere el ID de búsqueda")
        if schedule.get("activa"):
            if "meltwater" not in active or not search_id:
                raise MeasurementProblem(400, "La programación requiere una fuente Meltwater activa con ID de búsqueda")
            validate_creation({"cuenta_id": 1, "nombre": "validación", "fuentes": [meltwater],
                               "programacion_meltwater": schedule})
