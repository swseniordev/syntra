"""Casos de uso de Grupos: relaciones, estados, concurrencia y auditoría."""

import base64
import binascii
import hashlib
import json
from enum import Enum
from typing import Any

from app.modules.grupos.application.ports import GroupUnitOfWork
from app.modules.grupos.domain.rules import InvalidGroup, normalize


class GroupProblemKind(Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class GroupProblem(Exception):
    def __init__(self, kind: GroupProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def version_tag(row: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(row["actualizado_en"].isoformat().encode()).hexdigest() + '"'


def _cursor(query: str, state: str, cursor: str | None) -> tuple[str, int | None]:
    fingerprint = hashlib.sha256(json.dumps([query, state], ensure_ascii=False).encode()).hexdigest()[:16]
    if not cursor:
        return fingerprint, None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        marker, row_id = raw.split(":", 1)
        if marker != fingerprint or int(row_id) < 0:
            raise ValueError
        return fingerprint, int(row_id)
    except (UnicodeError, ValueError, binascii.Error):
        raise GroupProblem(GroupProblemKind.VALIDATION, "Cursor inválido para estos filtros") from None


class GroupUseCases:
    def __init__(self, uow: GroupUnitOfWork):
        self.uow = uow

    def list(self, query: str, state: str, order: str | None, cursor: str | None, limit: int) -> dict[str, Any]:
        if order is not None:
            raise GroupProblem(GroupProblemKind.VALIDATION, "El contrato aún no define valores para orden")
        query = query.strip()
        marker, after = _cursor(query, state, cursor)
        total, rows = self.uow.groups.list(query, state, after, limit + 1)
        items = rows[:limit]
        following = (base64.urlsafe_b64encode(f"{marker}:{items[-1]['id']}".encode()).decode().rstrip("=")
                     if len(rows) > limit else None)
        return {"items": items, "siguiente": following, "total_aprox": total}

    def get(self, group_id: int) -> dict[str, Any]:
        row = self.uow.groups.get(group_id)
        if row is None:
            raise GroupProblem(GroupProblemKind.NOT_FOUND, "Grupo no encontrado")
        return row

    def _validate(self, values: dict[str, Any]) -> dict[str, Any]:
        try:
            return normalize(values)
        except InvalidGroup as exc:
            raise GroupProblem(GroupProblemKind.VALIDATION, str(exc)) from exc

    def _references(self, values: dict[str, Any]) -> None:
        if not self.uow.groups.references_exist(values.get("usuario_ids", []), values.get("cuenta_ids", [])):
            raise GroupProblem(GroupProblemKind.VALIDATION, "Seleccione usuarios y cuentas vigentes")

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        values = self._validate(values)
        with self.uow:
            self.uow.groups.lock_names()
            if self.uow.groups.name_exists(values["nombre"]):
                raise GroupProblem(GroupProblemKind.CONFLICT, "Ya existe un grupo vigente con ese nombre")
            self._references(values)
            row = self.uow.groups.create(values, actor_id)
            self._audit("crear", actor_id, row, after=row)
            self.uow.commit()
        return row

    def edit(self, group_id: int, changes: dict[str, Any], expected: str | None, actor_id: int) -> dict[str, Any]:
        if expected is None:
            raise GroupProblem(GroupProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        changes = self._validate(changes)
        with self.uow:
            if "nombre" in changes:
                self.uow.groups.lock_names()
            before = self.uow.groups.get(group_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise GroupProblem(GroupProblemKind.NOT_FOUND, "Grupo no encontrado")
            if version_tag(before) != expected:
                raise GroupProblem(GroupProblemKind.PRECONDITION_FAILED, "El grupo cambió desde la última lectura")
            if not changes:
                return before
            if "nombre" in changes and self.uow.groups.name_exists(changes["nombre"], group_id):
                raise GroupProblem(GroupProblemKind.CONFLICT, "Ya existe un grupo vigente con ese nombre")
            self._references(changes)
            row = self.uow.groups.update(group_id, changes, actor_id)
            self._audit("editar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def delete(self, group_id: int, actor_id: int) -> None:
        with self.uow:
            before = self.uow.groups.get(group_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise GroupProblem(GroupProblemKind.NOT_FOUND, "Grupo no encontrado")
            row = self.uow.groups.update(group_id, {"estado_id": -1}, actor_id)
            self._audit("eliminar", actor_id, row, before=before, after=row)
            self.uow.commit()

    def restore(self, group_id: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            self.uow.groups.lock_names()
            before = self.uow.groups.get(group_id, for_update=True)
            if before is None:
                raise GroupProblem(GroupProblemKind.NOT_FOUND, "Grupo no encontrado")
            if before["estado_id"] != -1:
                raise GroupProblem(GroupProblemKind.VALIDATION, "El grupo no está eliminado")
            if self.uow.groups.name_exists(before["nombre"], group_id):
                raise GroupProblem(GroupProblemKind.CONFLICT, "Ya existe un grupo vigente con ese nombre")
            row = self.uow.groups.update(group_id, {"estado_id": 0}, actor_id)
            self._audit("restaurar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def change_state(self, group_id: int, state: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.groups.get(group_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise GroupProblem(GroupProblemKind.NOT_FOUND, "Grupo no encontrado")
            if before["estado_id"] == state:
                return before
            row = self.uow.groups.update(group_id, {"estado_id": state}, actor_id)
            self._audit("cambio_estado", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def _audit(self, action: str, actor_id: int, row: dict[str, Any], **values: Any) -> None:
        self.uow.audit.record(actor_id=actor_id, module="grupos", action=action,
                              entity_type="Grupo", entity_id=str(row["id"]), entity_name=row["nombre"], **values)
