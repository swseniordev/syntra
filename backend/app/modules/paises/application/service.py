"""Casos de uso de Países; controla estados, concurrencia y auditoría atómica."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from enum import Enum
from typing import Any

from app.modules.paises.application.ports import CountryUnitOfWork, DuplicateCode
from app.modules.paises.domain.rules import InvalidCountry, normalize


class CountryProblemKind(Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class CountryProblem(Exception):
    def __init__(self, kind: CountryProblemKind, detail: str):
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
        raise CountryProblem(CountryProblemKind.VALIDATION, "Cursor inválido para estos filtros") from None


def _normalize(values: dict[str, Any]) -> dict[str, Any]:
    try:
        return normalize(values)
    except InvalidCountry as exc:
        raise CountryProblem(CountryProblemKind.VALIDATION, str(exc)) from exc


class CountryUseCases:
    def __init__(self, uow: CountryUnitOfWork):
        self.uow = uow

    def list(self, query: str, state: str, order: str | None, cursor: str | None, limit: int) -> dict[str, Any]:
        if order is not None:
            raise CountryProblem(CountryProblemKind.VALIDATION, "El contrato aún no define valores para orden")
        query = query.strip()
        fingerprint = _fingerprint(query, state)
        after_id = _after(cursor, fingerprint) if cursor else None
        total, rows = self.uow.countries.list(query, state, after_id, limit + 1)
        items = rows[:limit]
        following = None
        if len(rows) > limit:
            following = base64.urlsafe_b64encode(f"{fingerprint}:{items[-1]['id']}".encode()).decode().rstrip("=")
        return {"items": items, "siguiente": following, "total_aprox": total}

    def get(self, country_id: int) -> dict[str, Any]:
        row = self.uow.countries.get(country_id)
        if row is None:
            raise CountryProblem(CountryProblemKind.NOT_FOUND, "País no encontrado")
        return row

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        values = _normalize(values)
        with self.uow:
            if self.uow.countries.code_exists(values["codigo"]):
                raise CountryProblem(CountryProblemKind.CONFLICT, "Ya existe un país vigente con ese código")
            try:
                row = self.uow.countries.create(values, actor_id)
            except DuplicateCode:
                raise CountryProblem(CountryProblemKind.CONFLICT, "Ya existe un país vigente con ese código") from None
            self._audit("crear", actor_id, row, after=row)
            self.uow.commit()
        return row

    def edit(self, country_id: int, changes: dict[str, Any], expected: str | None, actor_id: int) -> dict[str, Any]:
        if expected is None:
            raise CountryProblem(CountryProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        changes = _normalize(changes)
        with self.uow:
            before = self.uow.countries.get(country_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise CountryProblem(CountryProblemKind.NOT_FOUND, "País no encontrado")
            if version_tag(before) != expected:
                raise CountryProblem(CountryProblemKind.PRECONDITION_FAILED, "El país cambió desde la última lectura")
            if not changes:
                return before
            if "codigo" in changes and self.uow.countries.code_exists(changes["codigo"], country_id):
                raise CountryProblem(CountryProblemKind.CONFLICT, "Ya existe un país vigente con ese código")
            try:
                row = self.uow.countries.update(country_id, changes, actor_id)
            except DuplicateCode:
                raise CountryProblem(CountryProblemKind.CONFLICT, "Ya existe un país vigente con ese código") from None
            self._audit("editar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def delete(self, country_id: int, actor_id: int) -> None:
        with self.uow:
            before = self.uow.countries.get(country_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise CountryProblem(CountryProblemKind.NOT_FOUND, "País no encontrado")
            row = self.uow.countries.update(country_id, {"estado_id": -1}, actor_id)
            self._audit("eliminar", actor_id, row, before=before, after=row)
            self.uow.commit()

    def restore(self, country_id: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.countries.get(country_id, for_update=True)
            if before is None:
                raise CountryProblem(CountryProblemKind.NOT_FOUND, "País no encontrado")
            if before["estado_id"] != -1:
                raise CountryProblem(CountryProblemKind.VALIDATION, "El país no está eliminado")
            if self.uow.countries.code_exists(before["codigo"], country_id):
                raise CountryProblem(CountryProblemKind.CONFLICT, "Ya existe un país vigente con ese código")
            try:
                row = self.uow.countries.update(country_id, {"estado_id": 0}, actor_id)
            except DuplicateCode:
                raise CountryProblem(CountryProblemKind.CONFLICT, "Ya existe un país vigente con ese código") from None
            self._audit("restaurar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def change_state(self, country_id: int, state: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            before = self.uow.countries.get(country_id, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise CountryProblem(CountryProblemKind.NOT_FOUND, "País no encontrado")
            if before["estado_id"] == state:
                return before
            row = self.uow.countries.update(country_id, {"estado_id": state}, actor_id)
            self._audit("cambio_estado", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def _audit(self, action: str, actor_id: int, row: dict[str, Any], **values: Any) -> None:
        self.uow.audit.record(actor_id=actor_id, module="paises", action=action,
                              entity_type="País", entity_id=str(row["id"]), entity_name=row["nombre"], **values)
