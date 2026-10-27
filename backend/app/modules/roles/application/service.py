"""Operaciones de Roles sin FastAPI ni SQL."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from enum import Enum
from typing import Any

from app.modules.roles.application.ports import DuplicateRoleName, RoleUnitOfWork
from app.modules.roles.domain.rules import (
    InsufficientAuthority, InvalidRolePermissions, authorize_assignment, parse_permissions,
)


class RoleProblemKind(Enum):
    VALIDATION = "validation"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class RoleProblem(Exception):
    def __init__(self, kind: RoleProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def version_tag(row: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(row["actualizado_en"].isoformat().encode()).hexdigest() + '"'


def _fingerprint(query: str, state: str) -> str:
    return hashlib.sha256(json.dumps([query, state], ensure_ascii=False).encode()).hexdigest()[:16]


def _after(cursor: str, fingerprint: str) -> int:
    try:
        value = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        marker, role_id = value.split(":", 1)
        if marker != fingerprint or int(role_id) < 0:
            raise ValueError
        return int(role_id)
    except (UnicodeError, ValueError, binascii.Error):
        raise RoleProblem(RoleProblemKind.VALIDATION, "Cursor inválido para estos filtros") from None


def _name(value: str) -> str:
    name = " ".join(value.split())
    if not name:
        raise RoleProblem(RoleProblemKind.VALIDATION, "Nombre obligatorio")
    return name


class RoleUseCases:
    def __init__(self, uow: RoleUnitOfWork):
        self.uow = uow

    def list(self, query: str, state: str, order: str | None, cursor: str | None, limit: int) -> dict[str, Any]:
        if order is not None:
            raise RoleProblem(RoleProblemKind.VALIDATION, "El contrato aún no define valores para orden")
        query = query.strip()
        fingerprint = _fingerprint(query, state)
        after_id = _after(cursor, fingerprint) if cursor else None
        total, rows = self.uow.roles.list(query, state, after_id, limit + 1)
        items = rows[:limit]
        following = None
        if len(rows) > limit:
            following = base64.urlsafe_b64encode(f"{fingerprint}:{items[-1]['id']}".encode()).decode().rstrip("=")
        return {"items": items, "siguiente": following, "total_aprox": total}

    def get(self, role_id: int) -> dict[str, Any]:
        row = self.uow.roles.get(role_id)
        if row is None:
            raise RoleProblem(RoleProblemKind.NOT_FOUND, "Rol no encontrado")
        return row

    def catalog(self) -> dict[str, list[dict[str, str]]]:
        return {"items": self.uow.roles.catalog()}

    @staticmethod
    def _requested(value: dict[str, list[str]], actor_permissions: frozenset[str],
                   requested_ver_todas: bool, actor_ver_todas: bool) -> frozenset[tuple[str, str]]:
        try:
            pairs = parse_permissions(value)
            authorize_assignment(pairs, actor_permissions, requested_ver_todas=requested_ver_todas,
                                 actor_ver_todas=actor_ver_todas)
            return pairs
        except InsufficientAuthority as exc:
            raise RoleProblem(RoleProblemKind.FORBIDDEN, str(exc)) from exc
        except InvalidRolePermissions as exc:
            raise RoleProblem(RoleProblemKind.VALIDATION, str(exc)) from exc

    def create(self, values: dict[str, Any], actor_id: int, actor_permissions: frozenset[str],
               actor_ver_todas: bool) -> dict[str, Any]:
        values = dict(values)
        values["nombre"] = _name(values["nombre"])
        pairs = self._requested(values.pop("permisos"), actor_permissions, values.get("ver_todas", False), actor_ver_todas)
        with self.uow:
            if self.uow.roles.name_exists(values["nombre"]):
                raise RoleProblem(RoleProblemKind.CONFLICT, "Ya existe un rol vigente con ese nombre")
            try:
                row = self.uow.roles.create(values, pairs, actor_id)
            except DuplicateRoleName:
                raise RoleProblem(RoleProblemKind.CONFLICT, "Ya existe un rol vigente con ese nombre") from None
            self.uow.audit.record(actor_id=actor_id, module="roles", action="crear", entity_type="Rol",
                                  entity_id=str(row["id"]), entity_name=row["nombre"], after=row)
            self.uow.commit()
        return row

    def edit(self, role_id: int, changes: dict[str, Any], expected: str | None, actor_id: int,
             actor_permissions: frozenset[str], actor_ver_todas: bool) -> dict[str, Any]:
        if expected is None:
            raise RoleProblem(RoleProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        changes = dict(changes)
        if "nombre" in changes:
            changes["nombre"] = _name(changes["nombre"])
        with self.uow:
            before = self.uow.roles.get(role_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise RoleProblem(RoleProblemKind.NOT_FOUND, "Rol no encontrado")
            if version_tag(before) != expected:
                raise RoleProblem(RoleProblemKind.PRECONDITION_FAILED, "El rol cambió desde la última lectura")
            permissions = None
            if "permisos" in changes:
                permissions = self._requested(changes.pop("permisos"), actor_permissions,
                                              changes.get("ver_todas", before["ver_todas"]), actor_ver_todas)
            elif changes.get("ver_todas", False) and not actor_ver_todas:
                raise RoleProblem(RoleProblemKind.FORBIDDEN, "No puede conceder visibilidad completa")
            if self.uow.roles.is_assigned_to(role_id, actor_id):
                if changes.get("estado_id") == 0:
                    raise RoleProblem(RoleProblemKind.CONFLICT, "No puede inactivar su propio rol")
                if permissions is not None and ("roles", "editar") not in permissions:
                    raise RoleProblem(RoleProblemKind.CONFLICT, "No puede quitarse el permiso de editar roles")
            if not changes and permissions is None:
                return before
            if "nombre" in changes and self.uow.roles.name_exists(changes["nombre"], role_id):
                raise RoleProblem(RoleProblemKind.CONFLICT, "Ya existe un rol vigente con ese nombre")
            try:
                row = self.uow.roles.update(role_id, changes, permissions, actor_id)
            except DuplicateRoleName:
                raise RoleProblem(RoleProblemKind.CONFLICT, "Ya existe un rol vigente con ese nombre") from None
            self.uow.audit.record(actor_id=actor_id, module="roles", action="editar", entity_type="Rol",
                                  entity_id=str(role_id), entity_name=row["nombre"], before=before, after=row)
            self.uow.commit()
        return row

    def delete(self, role_id: int, actor_id: int) -> None:
        with self.uow:
            before = self.uow.roles.get(role_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise RoleProblem(RoleProblemKind.NOT_FOUND, "Rol no encontrado")
            if self.uow.roles.has_users(role_id):
                raise RoleProblem(RoleProblemKind.CONFLICT, "El rol tiene usuarios asociados")
            row = self.uow.roles.set_state(role_id, -1, actor_id)
            self.uow.audit.record(actor_id=actor_id, module="roles", action="eliminar", entity_type="Rol",
                                  entity_id=str(role_id), entity_name=row["nombre"], before=before, after=row)
            self.uow.commit()

    def restore(self, role_id: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.roles.get(role_id, for_update=True)
            if before is None:
                raise RoleProblem(RoleProblemKind.NOT_FOUND, "Rol no encontrado")
            if before["estado_id"] != -1:
                raise RoleProblem(RoleProblemKind.VALIDATION, "El rol no está eliminado")
            if self.uow.roles.name_exists(before["nombre"], role_id):
                raise RoleProblem(RoleProblemKind.CONFLICT, "Ya existe un rol vigente con ese nombre")
            try:
                row = self.uow.roles.set_state(role_id, 0, actor_id)
            except DuplicateRoleName:
                raise RoleProblem(RoleProblemKind.CONFLICT, "Ya existe un rol vigente con ese nombre") from None
            self.uow.audit.record(actor_id=actor_id, module="roles", action="restaurar", entity_type="Rol",
                                  entity_id=str(role_id), entity_name=row["nombre"], before=before, after=row)
            self.uow.commit()
        return row

    def change_state(self, role_id: int, state: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.roles.get(role_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise RoleProblem(RoleProblemKind.NOT_FOUND, "Rol no encontrado")
            if before["estado_id"] == state:
                return before
            if state == 0 and self.uow.roles.is_assigned_to(role_id, actor_id):
                raise RoleProblem(RoleProblemKind.CONFLICT, "No puede inactivar su propio rol")
            row = self.uow.roles.set_state(role_id, state, actor_id)
            self.uow.audit.record(actor_id=actor_id, module="roles", action="cambio_estado", entity_type="Rol",
                                  entity_id=str(role_id), entity_name=row["nombre"], before=before, after=row)
            self.uow.commit()
        return row
