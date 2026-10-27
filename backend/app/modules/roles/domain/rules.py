"""Único catálogo asignable de pares módulo:acción aprobados."""

from __future__ import annotations

from collections.abc import Mapping

# Fuente: docs/matriz_rbac_segunda_entrega.md. No es el producto cartesiano de
# cat.modulo y cat.accion: solo figuran acciones con respaldo contractual.
APPROVED_ACTIONS: Mapping[str, tuple[str, ...]] = {
    "actores": ("ver", "crear", "editar", "eliminar"),
    "auditoria": ("ver",),
    "clientes": ("ver", "crear", "editar", "eliminar"),
    "cruces": ("ver", "crear", "editar", "eliminar"),
    "cuentas": ("ver", "crear", "editar", "eliminar"),
    "dashboard": ("ver",),
    "fiscalizacion": ("ver", "editar", "ejecutar", "exportar"),
    "formatos": ("ver", "crear", "editar", "eliminar"),
    "grupos": ("ver", "crear", "editar", "eliminar"),
    "informes": ("ver", "exportar"),
    "llm": ("ver", "crear", "editar", "eliminar"),
    "mediciones": ("ver", "crear", "editar", "eliminar", "ejecutar"),
    "paises": ("ver", "crear", "editar", "eliminar"),
    "procesos": ("ver", "ejecutar"),
    "prompts": ("ver", "crear", "editar", "eliminar"),
    "regex": ("ver", "crear", "editar", "eliminar"),
    "registros": ("ver", "editar", "eliminar", "exportar"),
    "roles": ("ver", "crear", "editar", "eliminar"),
    "usuarios": ("ver", "crear", "editar", "eliminar"),
}
APPROVED_PAIRS = frozenset(
    (module, action) for module, actions in APPROVED_ACTIONS.items() for action in actions
)


class InvalidRolePermissions(ValueError):
    """La asignación excede el catálogo o los permisos del actor."""


class InsufficientAuthority(InvalidRolePermissions):
    """El actor carece del permiso o ámbito que intenta conceder."""


def parse_permissions(value: Mapping[str, list[str]]) -> frozenset[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for module, actions in value.items():
        if not isinstance(actions, list):
            raise InvalidRolePermissions("Cada módulo debe contener una lista de acciones")
        for action in actions:
            if not isinstance(action, str) or (module, action) not in APPROVED_PAIRS:
                raise InvalidRolePermissions("Permiso fuera del catálogo aprobado")
            result.add((module, action))
    return frozenset(result)


def authorize_assignment(
    requested: frozenset[tuple[str, str]], actor_permissions: frozenset[str],
    *, requested_ver_todas: bool, actor_ver_todas: bool,
) -> None:
    if not requested.issubset(APPROVED_PAIRS):
        raise InvalidRolePermissions("Permiso fuera del catálogo aprobado")
    if any(f"{module}:{action}" not in actor_permissions for module, action in requested):
        raise InsufficientAuthority("No puede conceder permisos que no posee")
    if requested_ver_todas and not actor_ver_todas:
        raise InsufficientAuthority("No puede conceder visibilidad completa")
