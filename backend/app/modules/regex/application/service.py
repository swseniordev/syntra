"""CRUD, versiones y prueba de Regex mediante contratos sustituibles."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from enum import Enum
from typing import Any

from app.modules.regex.application.ports import RegexEvaluator, RegexUnitOfWork
from app.modules.regex.domain.rules import InvalidRegex, normalize


class RegexProblemKind(Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class RegexProblem(Exception):
    def __init__(self, kind: RegexProblemKind, detail: str):
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
        raise RegexProblem(RegexProblemKind.VALIDATION, "Cursor inválido para estos filtros") from None


class RegexUseCases:
    def __init__(self, uow: RegexUnitOfWork, evaluator: RegexEvaluator):
        self.uow = uow
        self.evaluator = evaluator

    def list(self, query: str, state: str, order: str | None, cursor: str | None, limit: int) -> dict[str, Any]:
        if order is not None:
            raise RegexProblem(RegexProblemKind.VALIDATION, "El contrato aún no define valores para orden")
        query = query.strip()
        fingerprint = _fingerprint(query, state)
        after_id = _after(cursor, fingerprint) if cursor else None
        total, rows = self.uow.regex.list(query, state, after_id, limit + 1)
        items = rows[:limit]
        following = None
        if len(rows) > limit:
            following = base64.urlsafe_b64encode(f"{fingerprint}:{items[-1]['id']}".encode()).decode().rstrip("=")
        return {"items": items, "siguiente": following, "total_aprox": total}

    def get(self, regex_id: int) -> dict[str, Any]:
        row = self.uow.regex.get(regex_id)
        if row is None:
            raise RegexProblem(RegexProblemKind.NOT_FOUND, "Regex no encontrada")
        return row

    def versions(self, regex_id: int) -> list[dict[str, Any]]:
        self.get(regex_id)
        return self.uow.regex.versions(regex_id)

    def test(self, condition: str, flags: str, text: str) -> dict[str, Any]:
        if flags not in ("", "i"):
            return {"valida": False, "cumple": False, "coincidencias": [],
                    "error": "Solo se admite el indicador i para ignorar mayúsculas"}
        return self.evaluator.test(condition, flags, text)

    def _normalize(self, values: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return normalize(values, current)
        except InvalidRegex as exc:
            raise RegexProblem(RegexProblemKind.VALIDATION, str(exc)) from exc

    def _validate_match(self, values: dict[str, Any]) -> None:
        result = self.test(values["condicion"], values["flags"], values["texto_prueba"])
        if not result["valida"]:
            raise RegexProblem(RegexProblemKind.VALIDATION, result["error"] or "La condición RE2 es inválida")
        if not result["cumple"]:
            raise RegexProblem(RegexProblemKind.VALIDATION, "La condición no coincide con el texto de prueba")

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        values = self._normalize(values)
        values.setdefault("flags", "i")
        self._validate_match(values)
        with self.uow:
            self.uow.regex.lock_name(values["nombre"])
            if self.uow.regex.name_exists(values["nombre"]):
                raise RegexProblem(RegexProblemKind.CONFLICT, "Ya existe una regex vigente con ese nombre")
            row = self.uow.regex.create(values, actor_id)
            self._audit("crear", actor_id, row, after=row)
            self.uow.commit()
        return row

    def edit(self, regex_id: int, changes: dict[str, Any], expected: str | None, actor_id: int) -> dict[str, Any]:
        if expected is None:
            raise RegexProblem(RegexProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        preliminary = self.get(regex_id)
        if preliminary["estado_id"] == -1:
            raise RegexProblem(RegexProblemKind.NOT_FOUND, "Regex no encontrada")
        changes = self._normalize(changes, preliminary)
        merged = {**preliminary, **changes}
        if any(field in changes for field in ("condicion", "flags", "texto_prueba")):
            self._validate_match(merged)
        with self.uow:
            if "nombre" in changes:
                self.uow.regex.lock_name(changes["nombre"])
            before = self.uow.regex.get(regex_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise RegexProblem(RegexProblemKind.NOT_FOUND, "Regex no encontrada")
            if version_tag(before) != expected:
                raise RegexProblem(RegexProblemKind.PRECONDITION_FAILED, "La regex cambió desde la última lectura")
            if not changes:
                return before
            if "nombre" in changes and self.uow.regex.name_exists(changes["nombre"], regex_id):
                raise RegexProblem(RegexProblemKind.CONFLICT, "Ya existe una regex vigente con ese nombre")
            row = self.uow.regex.update(regex_id, changes, actor_id)
            self._audit("editar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def delete(self, regex_id: int, actor_id: int) -> None:
        with self.uow:
            before = self.uow.regex.get(regex_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise RegexProblem(RegexProblemKind.NOT_FOUND, "Regex no encontrada")
            row = self.uow.regex.update(regex_id, {"estado_id": -1}, actor_id)
            self._audit("eliminar", actor_id, row, before=before, after=row)
            self.uow.commit()

    def restore(self, regex_id: int, actor_id: int) -> dict[str, Any]:
        preliminary = self.get(regex_id)
        with self.uow:
            self.uow.regex.lock_name(preliminary["nombre"])
            before = self.uow.regex.get(regex_id, for_update=True)
            if before is None:
                raise RegexProblem(RegexProblemKind.NOT_FOUND, "Regex no encontrada")
            if before["estado_id"] != -1:
                raise RegexProblem(RegexProblemKind.VALIDATION, "La regex no está eliminada")
            if self.uow.regex.name_exists(before["nombre"], regex_id):
                raise RegexProblem(RegexProblemKind.CONFLICT, "Ya existe una regex vigente con ese nombre")
            row = self.uow.regex.update(regex_id, {"estado_id": 0}, actor_id)
            self._audit("restaurar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def change_state(self, regex_id: int, state: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.regex.get(regex_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise RegexProblem(RegexProblemKind.NOT_FOUND, "Regex no encontrada")
            if before["estado_id"] == state:
                return before
            row = self.uow.regex.update(regex_id, {"estado_id": state}, actor_id)
            self._audit("cambio_estado", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def _audit(self, action: str, actor_id: int, row: dict[str, Any], **values: Any) -> None:
        self.uow.audit.record(actor_id=actor_id, module="regex", action=action,
                              entity_type="Regex", entity_id=str(row["id"]), entity_name=row["nombre"], **values)
