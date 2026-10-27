"""Casos de uso de escritura de Usuarios y encolado atómico de correo."""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Protocol, Self

from app.modules.auditoria.application.ports import AuditWriter
from app.modules.usuarios.domain.rules import InvalidUser, normalize


class UserProblemKind(Enum):
    VALIDATION = "validation"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class UserProblem(Exception):
    def __init__(self, kind: UserProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def version_tag(row: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(row["actualizado_en"].isoformat().encode()).hexdigest() + '"'


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "version_token"}


class UserWriter(Protocol):
    def get(self, user_id: int, *, for_update: bool = False) -> dict[str, Any] | None: ...
    def role_authorized(self, role_id: int, permissions: frozenset[str], ver_todas: bool) -> bool: ...
    def groups_exist(self, group_ids: list[int]) -> bool: ...
    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]: ...
    def update(self, user_id: int, values: dict[str, Any], actor_id: int) -> dict[str, Any]: ...
    def enqueue_password(self, user_id: int, version: int, actor_id: int, reason: str) -> int: ...
    def revoke_sessions(self, user_id: int) -> None: ...


class UserUnitOfWork(Protocol):
    users: UserWriter
    audit: AuditWriter
    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...
    def commit(self) -> None: ...


class UserCommands:
    def __init__(self, uow: UserUnitOfWork):
        self.uow = uow

    def _normalize(self, values: dict[str, Any]) -> dict[str, Any]:
        try:
            return normalize(values)
        except InvalidUser as exc:
            raise UserProblem(UserProblemKind.VALIDATION, str(exc)) from exc

    def _references(self, values: dict[str, Any], permissions: frozenset[str], ver_todas: bool) -> None:
        if "rol_id" in values and not self.uow.users.role_authorized(values["rol_id"], permissions, ver_todas):
            raise UserProblem(UserProblemKind.FORBIDDEN, "No puedes asignar ese rol")
        if "grupo_ids" in values and not self.uow.users.groups_exist(values["grupo_ids"]):
            raise UserProblem(UserProblemKind.VALIDATION, "Selecciona grupos vigentes")

    def _audit(self, action: str, actor_id: int, row: dict[str, Any], **changes: Any) -> None:
        self.uow.audit.record(actor_id=actor_id, module="usuarios", action=action,
                              entity_type="Usuario", entity_id=str(row["id"]), entity_name=row["nombre"], **changes)

    def create(self, values: dict[str, Any], actor_id: int, permissions: frozenset[str], ver_todas: bool) -> dict[str, Any]:
        values = self._normalize(values)
        with self.uow:
            self._references(values, permissions, ver_todas)
            try:
                row = self.uow.users.create(values, actor_id)
            except ValueError as exc:
                raise UserProblem(UserProblemKind.CONFLICT, str(exc)) from exc
            self.uow.users.enqueue_password(row["id"], 1, actor_id, "alta")
            self._audit("crear", actor_id, row, after=row)
            self.uow.commit()
        return public_user(row)

    def edit(self, user_id: int, values: dict[str, Any], expected: str | None, actor_id: int,
             permissions: frozenset[str], ver_todas: bool) -> dict[str, Any]:
        if expected is None:
            raise UserProblem(UserProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        values = self._normalize(values)
        if user_id == actor_id and values.get("estado_id") == 0:
            raise UserProblem(UserProblemKind.VALIDATION, "No puedes inactivar tu propio usuario")
        with self.uow:
            before = self.uow.users.get(user_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise UserProblem(UserProblemKind.NOT_FOUND, "Usuario no encontrado")
            if version_tag(before) != expected:
                raise UserProblem(UserProblemKind.PRECONDITION_FAILED, "El usuario cambió desde la última lectura")
            if not values:
                return public_user(before)
            self._references(values, permissions, ver_todas)
            try:
                row = self.uow.users.update(user_id, values, actor_id)
            except ValueError as exc:
                raise UserProblem(UserProblemKind.CONFLICT, str(exc)) from exc
            if ("rol_id" in values and values["rol_id"] != before["rol_id"]) or values.get("estado_id") == 0:
                self.uow.users.revoke_sessions(user_id)
            self._audit("editar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return public_user(row)

    def change_state(self, user_id: int, state: int, actor_id: int) -> dict[str, Any]:
        if user_id == actor_id and state != 1:
            raise UserProblem(UserProblemKind.VALIDATION, "No puedes inactivar tu propio usuario")
        with self.uow:
            before = self.uow.users.get(user_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise UserProblem(UserProblemKind.NOT_FOUND, "Usuario no encontrado")
            if before["estado_id"] == state:
                return public_user(before)
            row = self.uow.users.update(user_id, {"estado_id": state}, actor_id)
            if state == 0:
                self.uow.users.revoke_sessions(user_id)
            self._audit("cambio_estado", actor_id, row, before=before, after=row)
            self.uow.commit()
        return public_user(row)

    def delete(self, user_id: int, actor_id: int) -> None:
        if user_id == actor_id:
            raise UserProblem(UserProblemKind.CONFLICT, "No puedes eliminar tu propio usuario")
        with self.uow:
            before = self.uow.users.get(user_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise UserProblem(UserProblemKind.NOT_FOUND, "Usuario no encontrado")
            row = self.uow.users.update(user_id, {"estado_id": -1}, actor_id)
            self.uow.users.revoke_sessions(user_id)
            self._audit("eliminar", actor_id, row, before=before, after=row)
            self.uow.commit()

    def restore(self, user_id: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.users.get(user_id, for_update=True)
            if before is None:
                raise UserProblem(UserProblemKind.NOT_FOUND, "Usuario no encontrado")
            if before["estado_id"] != -1:
                raise UserProblem(UserProblemKind.VALIDATION, "El usuario no está eliminado")
            row = self.uow.users.update(user_id, {"estado_id": 0}, actor_id)
            self._audit("restaurar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return public_user(row)

    def resend(self, user_id: int, actor_id: int) -> int:
        with self.uow:
            before = self.uow.users.get(user_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise UserProblem(UserProblemKind.NOT_FOUND, "Usuario no encontrado")
            if before["estado_id"] != 1:
                raise UserProblem(UserProblemKind.VALIDATION, "Activa al usuario antes de reenviar el correo")
            # Revoca antes del envío. La tarea nueva es la única que puede aplicar
            # la versión esperada; una tarea antigua no puede sobrescribirla.
            row = self.uow.users.update(user_id, {"version_token": before["version_token"] + 1}, actor_id)
            self.uow.users.revoke_sessions(user_id)
            process_id = self.uow.users.enqueue_password(user_id, row["version_token"], actor_id, "reenvio")
            self._audit("reenviar", actor_id, row, detail="correo_credencial_encolado")
            self.uow.commit()
        return process_id
