"""Casos de uso de Prompts: predeterminado único y versiones inmutables."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from enum import Enum
from typing import Any

from app.modules.prompts.application.ports import DefaultCollision, PromptUnitOfWork
from app.modules.prompts.domain.rules import InvalidPrompt, NETWORKS, PROMPT_TYPES, normalize


class PromptProblemKind(Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class PromptProblem(Exception):
    def __init__(self, kind: PromptProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def version_tag(row: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(row["actualizado_en"].isoformat().encode()).hexdigest() + '"'


def _fingerprint(query: str, state: str, kind: str | None, network: str | None) -> str:
    return hashlib.sha256(json.dumps([query, state, kind, network], ensure_ascii=False).encode()).hexdigest()[:16]


def _after(cursor: str, fingerprint: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        marker, row_id = raw.split(":", 1)
        if marker != fingerprint or int(row_id) < 0:
            raise ValueError
        return int(row_id)
    except (UnicodeError, ValueError, binascii.Error):
        raise PromptProblem(PromptProblemKind.VALIDATION, "Cursor inválido para estos filtros") from None


def _normalize(values: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return normalize(values, current)
    except InvalidPrompt as exc:
        raise PromptProblem(PromptProblemKind.VALIDATION, str(exc)) from exc


class PromptUseCases:
    def __init__(self, uow: PromptUnitOfWork):
        self.uow = uow

    def list(self, query: str, state: str, order: str | None, kind: str | None, network: str | None,
             cursor: str | None, limit: int) -> dict[str, Any]:
        if order is not None:
            raise PromptProblem(PromptProblemKind.VALIDATION, "El contrato aún no define valores para orden")
        if kind is not None and kind not in PROMPT_TYPES:
            raise PromptProblem(PromptProblemKind.VALIDATION, "Tipo de prompt inválido")
        if network is not None and network != "_" and network not in NETWORKS:
            raise PromptProblem(PromptProblemKind.VALIDATION, "Red no admitida")
        query = query.strip()
        fingerprint = _fingerprint(query, state, kind, network)
        after_id = _after(cursor, fingerprint) if cursor else None
        total, rows = self.uow.prompts.list(query, state, kind, network, after_id, limit + 1)
        items = rows[:limit]
        following = None
        if len(rows) > limit:
            following = base64.urlsafe_b64encode(f"{fingerprint}:{items[-1]['id']}".encode()).decode().rstrip("=")
        return {"items": items, "siguiente": following, "total_aprox": total}

    def get(self, prompt_id: int) -> dict[str, Any]:
        row = self.uow.prompts.get(prompt_id)
        if row is None:
            raise PromptProblem(PromptProblemKind.NOT_FOUND, "Prompt no encontrado")
        return row

    def versions(self, prompt_id: int) -> list[dict[str, Any]]:
        if self.uow.prompts.get(prompt_id) is None:
            raise PromptProblem(PromptProblemKind.NOT_FOUND, "Prompt no encontrado")
        return self.uow.prompts.versions(prompt_id)

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        values = _normalize(values)
        with self.uow:
            if values.get("por_defecto", False):
                self.uow.prompts.lock_default_scope(values["tipo"], values.get("red"))
                demoted = self.uow.prompts.demote_default(values["tipo"], values.get("red"), None, actor_id)
                self._audit_demotions(demoted, actor_id)
            try:
                row = self.uow.prompts.create(values, actor_id)
            except DefaultCollision:
                raise PromptProblem(PromptProblemKind.CONFLICT, "Ya existe un prompt activo por defecto para ese tipo y red") from None
            self._audit("crear", actor_id, row, after=row)
            self.uow.commit()
        return row

    def edit(self, prompt_id: int, changes: dict[str, Any], expected: str | None, actor_id: int) -> dict[str, Any]:
        if expected is None:
            raise PromptProblem(PromptProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        preliminary = self.uow.prompts.get(prompt_id)
        if preliminary is None or preliminary["estado_id"] == -1:
            raise PromptProblem(PromptProblemKind.NOT_FOUND, "Prompt no encontrado")
        changes = _normalize(changes, preliminary)
        target_default = changes.get("por_defecto", preliminary["por_defecto"])
        target_kind = changes.get("tipo", preliminary["tipo"])
        target_network = changes.get("red", preliminary["red"])
        with self.uow:
            if target_default:
                self.uow.prompts.lock_default_scope(target_kind, target_network)
            before = self.uow.prompts.get(prompt_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise PromptProblem(PromptProblemKind.NOT_FOUND, "Prompt no encontrado")
            if version_tag(before) != expected:
                raise PromptProblem(PromptProblemKind.PRECONDITION_FAILED, "El prompt cambió desde la última lectura")
            if not changes:
                return before
            if target_default:
                demoted = self.uow.prompts.demote_default(target_kind, target_network, prompt_id, actor_id)
                self._audit_demotions(demoted, actor_id)
            try:
                row = self.uow.prompts.update(prompt_id, changes, actor_id)
            except DefaultCollision:
                raise PromptProblem(PromptProblemKind.CONFLICT, "Ya existe un prompt activo por defecto para ese tipo y red") from None
            self._audit("editar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def delete(self, prompt_id: int, actor_id: int) -> None:
        with self.uow:
            before = self.uow.prompts.get(prompt_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise PromptProblem(PromptProblemKind.NOT_FOUND, "Prompt no encontrado")
            row = self.uow.prompts.update(prompt_id, {"estado_id": -1}, actor_id)
            self._audit("eliminar", actor_id, row, before=before, after=row)
            self.uow.commit()

    def restore(self, prompt_id: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.prompts.get(prompt_id, for_update=True)
            if before is None:
                raise PromptProblem(PromptProblemKind.NOT_FOUND, "Prompt no encontrado")
            if before["estado_id"] != -1:
                raise PromptProblem(PromptProblemKind.VALIDATION, "El prompt no está eliminado")
            row = self.uow.prompts.update(prompt_id, {"estado_id": 0, "por_defecto": False}, actor_id)
            self._audit("restaurar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def change_state(self, prompt_id: int, state: int, actor_id: int) -> dict[str, Any]:
        preliminary = self.uow.prompts.get(prompt_id)
        if preliminary is None or preliminary["estado_id"] == -1:
            raise PromptProblem(PromptProblemKind.NOT_FOUND, "Prompt no encontrado")
        with self.uow:
            if state == 1 and preliminary["por_defecto"]:
                self.uow.prompts.lock_default_scope(preliminary["tipo"], preliminary["red"])
            before = self.uow.prompts.get(prompt_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise PromptProblem(PromptProblemKind.NOT_FOUND, "Prompt no encontrado")
            if before["estado_id"] == state:
                return before
            if state == 1 and before["por_defecto"]:
                demoted = self.uow.prompts.demote_default(before["tipo"], before["red"], prompt_id, actor_id)
                self._audit_demotions(demoted, actor_id)
            changes = {"estado_id": state, **({"por_defecto": False} if state == 0 else {})}
            row = self.uow.prompts.update(prompt_id, changes, actor_id)
            self._audit("cambio_estado", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def _audit(self, action: str, actor_id: int, row: dict[str, Any], **values: Any) -> None:
        self.uow.audit.record(actor_id=actor_id, module="prompts", action=action,
                              entity_type="Prompt", entity_id=str(row["id"]), entity_name=row["nombre"], **values)

    def _audit_demotions(self, demoted: list[tuple[dict[str, Any], dict[str, Any]]], actor_id: int) -> None:
        for before, after in demoted:
            self._audit("editar", actor_id, after, before=before, after=after)
