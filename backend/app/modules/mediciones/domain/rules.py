"""Validaciones de dominio independientes de HTTP y PostgreSQL."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class InvalidMeasurement(ValueError):
    pass


def validate_creation(values: dict[str, Any]) -> None:
    if not isinstance(values.get("cuenta_id"), int) or values["cuenta_id"] < 1:
        raise InvalidMeasurement("Seleccione una cuenta válida")
    name = values.get("nombre")
    if not isinstance(name, str) or not name.strip():
        raise InvalidMeasurement("El nombre de la medición es obligatorio")
    clusters = values.get("clusters") or {}
    count = clusters.get("num_clusters", 15)
    subcount = clusters.get("num_subclusters", 3)
    if type(count) is not int or not 2 <= count <= 30:
        raise InvalidMeasurement("El número de clusters debe estar entre 2 y 30")
    if type(subcount) is not int or not 1 <= subcount <= 10:
        raise InvalidMeasurement("El número de subclusters debe estar entre 1 y 10")
    fuentes = values.get("fuentes", [])
    if not isinstance(fuentes, list):
        raise InvalidMeasurement("La configuración de fuentes no es válida")
    origins = [item.get("origen") for item in fuentes if isinstance(item, dict) and item.get("activo", True)]
    all_origins = [item.get("origen") for item in fuentes if isinstance(item, dict)]
    if len(all_origins) != len(set(all_origins)):
        raise InvalidMeasurement("No repita fuentes de la medición")
    scrapers = values.get("scrapers", [])
    if not isinstance(scrapers, list):
        raise InvalidMeasurement("La configuración de scrapers no es válida")
    if not origins and not scrapers:
        raise InvalidMeasurement("Active al menos una fuente o configure un scraper")
    active_meltwater = next((item for item in fuentes if item.get("origen") == "meltwater" and item.get("activo", True)), None)
    meltwater_id = ((active_meltwater or {}).get("config") or {}).get("busqueda_id")
    if active_meltwater and (not isinstance(meltwater_id, str) or not meltwater_id.strip()):
        raise InvalidMeasurement("Meltwater requiere el ID de búsqueda")
    regex = (values.get("regex") or {}).get("regex_ids_ordenados", [])
    if len(regex) != len(set(regex)):
        raise InvalidMeasurement("No repita expresiones regulares")
    prompts = values.get("prompts", [])
    keys = [(item.get("tipo"), item.get("red")) for item in prompts if isinstance(item, dict)]
    if len(keys) != len(set(keys)):
        raise InvalidMeasurement("No repita prompts para el mismo tipo y red")
    for section in (values.get("programacion_meltwater") or {}, values.get("ventana") or {}):
        if not isinstance(section, dict):
            raise InvalidMeasurement("La configuración de fechas no es válida")
    schedule = values.get("programacion_meltwater") or {}
    if schedule.get("activa"):
        meltwater = next((item for item in fuentes if item.get("origen") == "meltwater" and item.get("activo", True)), None)
        search_id = ((meltwater or {}).get("config") or {}).get("busqueda_id")
        if not isinstance(search_id, str) or not search_id.strip():
            raise InvalidMeasurement("La programación requiere un ID de búsqueda Meltwater")
        _validate_window(schedule.get("inicio"), schedule.get("fin"), "La programación de Meltwater")
        frequency = schedule.get("frecuencia_min")
        if type(frequency) is not int or frequency < 15:
            raise InvalidMeasurement("La frecuencia mínima de Meltwater es de 15 minutos")
    for scraper in scrapers:
        if not isinstance(scraper, dict):
            raise InvalidMeasurement("La configuración de scrapers no es válida")
        _validate_window(scraper.get("inicio"), scraper.get("fin"), "El scraper")
    if (values.get("estado_id", 1) not in (0, 1)
            or type(values.get("estado_id", 1)) is not int):
        raise InvalidMeasurement("El estado inicial de la medición no es válido")


def _validate_window(start: Any, end: Any, label: str) -> None:
    if isinstance(start, str):
        try:
            start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            start = None
    if isinstance(end, str):
        try:
            end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError:
            end = None
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise InvalidMeasurement(f"{label} requiere fechas inicial y final válidas")
    if start.tzinfo is None or end.tzinfo is None:
        raise InvalidMeasurement(f"{label} requiere fechas con zona horaria")
    if end <= start:
        raise InvalidMeasurement(f"La fecha final de {label.lower()} debe ser posterior a la inicial")


def retry_delay_ms(attempts: int, maximum: int, waits_ms: list[int] | tuple[int, ...]) -> int | None:
    """Devuelve espera configurada tras un fallo, o None al agotar ejecuciones."""
    if attempts < 1 or maximum < 1 or len(waits_ms) != maximum - 1:
        raise InvalidMeasurement("La política de reintentos de preparación no es válida")
    if any(type(wait) is not int or wait < 0 for wait in waits_ms):
        raise InvalidMeasurement("La política de reintentos de preparación no es válida")
    if attempts >= maximum:
        return None
    return waits_ms[attempts - 1]
