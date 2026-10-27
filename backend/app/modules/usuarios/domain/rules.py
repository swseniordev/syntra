"""Normalización de campos públicos de Usuarios, independiente de HTTP y SQL."""

import re
from typing import Any


class InvalidUser(ValueError):
    pass


def normalize(values: dict[str, Any]) -> dict[str, Any]:
    result = dict(values)
    if "nombre" in result:
        if not isinstance(result["nombre"], str):
            raise InvalidUser("El nombre es obligatorio")
        result["nombre"] = " ".join(result["nombre"].split())
        if not result["nombre"]:
            raise InvalidUser("El nombre es obligatorio")
    if "email" in result:
        if not isinstance(result["email"], str):
            raise InvalidUser("El correo es obligatorio")
        result["email"] = result["email"].strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result["email"]):
            raise InvalidUser("Correo electrónico inválido")
    if "telefono" in result and result["telefono"] is not None:
        result["telefono"] = result["telefono"].strip() or None
    if "grupo_ids" in result:
        ids = result["grupo_ids"]
        if ids is None or any(type(identifier) is not int or identifier < 1 for identifier in ids):
            raise InvalidUser("Los grupos deben ser identificadores positivos")
        if len(ids) != len(set(ids)):
            raise InvalidUser("Hay grupos repetidos")
        result["grupo_ids"] = sorted(ids)
    return result
