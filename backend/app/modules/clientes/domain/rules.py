"""Reglas puras de Clientes: sin HTTP ni persistencia."""

import re
from typing import Any


class ClientRuleError(ValueError):
    pass


EDITABLE_FIELDS = frozenset({"nombre", "rfc", "sector", "contacto"})


def ensure_editable_fields(changes: dict[str, Any]) -> None:
    if not changes.keys() <= EDITABLE_FIELDS:
        raise ClientRuleError("Campo de cliente no editable")


def normalize_name(value: str) -> str:
    if not isinstance(value, str):
        raise ClientRuleError("Nombre obligatorio")
    normalized = " ".join(value.split())
    if not normalized:
        raise ClientRuleError("Nombre obligatorio")
    return normalized


def normalize_optional(value: str | None, *, collapse_spaces: bool = False, uppercase: bool = False) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()) if collapse_spaces else value.strip()
    return (normalized.upper() if uppercase else normalized) or None


def normalize_contact(value: str | None) -> str | None:
    normalized = normalize_optional(value)
    if normalized is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
        raise ClientRuleError("Contacto debe ser un correo válido")
    return normalized


def normalize_fields(values: dict[str, Any]) -> dict[str, Any]:
    normalized = values.copy()
    if "nombre" in normalized:
        normalized["nombre"] = normalize_name(normalized["nombre"])
    if "rfc" in normalized:
        normalized["rfc"] = normalize_optional(normalized["rfc"])
    if "sector" in normalized:
        normalized["sector"] = normalize_optional(normalized["sector"], collapse_spaces=True, uppercase=True)
    if "contacto" in normalized:
        normalized["contacto"] = normalize_contact(normalized["contacto"])
    return normalized


def ensure_deletable(account_states: list[int]) -> None:
    if 1 in account_states:
        raise ClientRuleError(
            "El cliente tiene cuentas asociadas activas. Para eliminarlo, primero debes desactivar las cuentas relacionadas"
        )


def ensure_restorable(state: int) -> None:
    if state != -1:
        raise ClientRuleError("Solo se puede restaurar un cliente eliminado")


def ensure_vigente_state(state: int) -> None:
    if state not in (0, 1):
        raise ClientRuleError("Estado de cliente inválido")
