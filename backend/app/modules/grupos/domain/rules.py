"""Validación de grupos independiente de HTTP y PostgreSQL."""

from typing import Any


class InvalidGroup(ValueError):
    pass


def normalize(values: dict[str, Any]) -> dict[str, Any]:
    result = dict(values)
    if "nombre" in result:
        if result["nombre"] is None:
            raise InvalidGroup("El nombre es obligatorio")
        result["nombre"] = " ".join(result["nombre"].split())
        if not result["nombre"]:
            raise InvalidGroup("El nombre es obligatorio")
    if "descripcion" in result and result["descripcion"] is not None:
        result["descripcion"] = " ".join(result["descripcion"].split()) or None
    for field in ("usuario_ids", "cuenta_ids"):
        if field in result:
            ids = result[field]
            if ids is None or any(type(value) is not int or value <= 0 for value in ids):
                raise InvalidGroup(f"{field} debe contener identificadores positivos")
            if len(ids) != len(set(ids)):
                raise InvalidGroup(f"{field} contiene identificadores repetidos")
            result[field] = sorted(ids)
    return result
