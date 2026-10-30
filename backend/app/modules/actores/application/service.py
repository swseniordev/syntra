"""Casos de uso de Actores; controla estados, concurrencia y auditoría atómica."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from enum import Enum
from typing import Any

from app.modules.actores.application.ports import ActorUnitOfWork, UnknownNetwork
from app.modules.actores.domain.rules import InvalidActor, normalize


class ActorProblemKind(Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class ActorProblem(Exception):
    def __init__(self, kind: ActorProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def version_tag(row: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(row["actualizado_en"].isoformat().encode()).hexdigest() + '"'


def _fingerprint(query: str, state: str) -> str:
    return hashlib.sha256(json.dumps([query, state], ensure_ascii=False).encode()).hexdigest()[:16]


def _after(cursor: str, fingerprint: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        marker, row_id = raw.split(":", 1)
        if marker != fingerprint or int(row_id) < 0:
            raise ValueError
        return int(row_id)
    except (UnicodeError, ValueError, binascii.Error):
        raise ActorProblem(ActorProblemKind.VALIDATION, "Cursor inválido para estos filtros") from None


def _normalize(values: dict[str, Any]) -> dict[str, Any]:
    try:
        return normalize(values)
    except InvalidActor as exc:
        raise ActorProblem(ActorProblemKind.VALIDATION, str(exc)) from exc


class ActorUseCases:
    def __init__(self, uow: ActorUnitOfWork):
        self.uow = uow

    def list(self, query: str, state: str, order: str | None, cursor: str | None, limit: int) -> dict[str, Any]:
        if order is not None:
            raise ActorProblem(ActorProblemKind.VALIDATION, "El contrato aún no define valores para orden")
        query = query.strip()
        fingerprint = _fingerprint(query, state)
        after_id = _after(cursor, fingerprint) if cursor else None
        total, rows = self.uow.actors.list(query, state, after_id, limit + 1)
        items = rows[:limit]
        following = None
        if len(rows) > limit:
            following = base64.urlsafe_b64encode(f"{fingerprint}:{items[-1]['id']}".encode()).decode().rstrip("=")
        return {"items": items, "siguiente": following, "total_aprox": total}

    def get(self, actor_id: int) -> dict[str, Any]:
        row = self.uow.actors.get(actor_id)
        if row is None:
            raise ActorProblem(ActorProblemKind.NOT_FOUND, "Actor no encontrado")
        return row

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        values = _normalize(values)
        with self.uow:
            try:
                row = self.uow.actors.create(values, actor_id)
            except UnknownNetwork:
                raise ActorProblem(ActorProblemKind.VALIDATION, "La red no existe en el catálogo") from None
            self._audit("crear", actor_id, row, after=row)
            self.uow.commit()
        return row

    def edit(self, actor_id: int, changes: dict[str, Any], expected: str | None, user_id: int) -> dict[str, Any]:
        if expected is None:
            raise ActorProblem(ActorProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        changes = _normalize(changes)
        with self.uow:
            before = self.uow.actors.get(actor_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise ActorProblem(ActorProblemKind.NOT_FOUND, "Actor no encontrado")
            if version_tag(before) != expected:
                raise ActorProblem(ActorProblemKind.PRECONDITION_FAILED, "El actor cambió desde la última lectura")
            if not changes:
                return before
            try:
                row = self.uow.actors.update(actor_id, changes, user_id)
            except UnknownNetwork:
                raise ActorProblem(ActorProblemKind.VALIDATION, "La red no existe en el catálogo") from None
            self._audit("editar", user_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def delete(self, actor_id: int, user_id: int) -> None:
        with self.uow:
            before = self.uow.actors.get(actor_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise ActorProblem(ActorProblemKind.NOT_FOUND, "Actor no encontrado")
            row = self.uow.actors.update(actor_id, {"estado_id": -1}, user_id)
            self._audit("eliminar", user_id, row, before=before, after=row)
            self.uow.commit()

    def restore(self, actor_id: int, user_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.actors.get(actor_id, for_update=True)
            if before is None:
                raise ActorProblem(ActorProblemKind.NOT_FOUND, "Actor no encontrado")
            if before["estado_id"] != -1:
                raise ActorProblem(ActorProblemKind.VALIDATION, "El actor no está eliminado")
            row = self.uow.actors.update(actor_id, {"estado_id": 0}, user_id)
            self._audit("restaurar", user_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def change_state(self, actor_id: int, state: int, user_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.actors.get(actor_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise ActorProblem(ActorProblemKind.NOT_FOUND, "Actor no encontrado")
            if before["estado_id"] == state:
                return before
            row = self.uow.actors.update(actor_id, {"estado_id": state}, user_id)
            self._audit("cambio_estado", user_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def _audit(self, action: str, actor_id: int, row: dict[str, Any], **values: Any) -> None:
        self.uow.audit.record(actor_id=actor_id, module="actores", action=action,
                              entity_type="Actor", entity_id=str(row["id"]), entity_name=row["nombre"], **values)
