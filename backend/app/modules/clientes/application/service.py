"""Casos de uso de Clientes; solo dependen de reglas puras y puertos."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

from app.modules.clientes.application.errors import ClientProblem, ProblemKind
from app.modules.clientes.application.ports import ClientUnitOfWork, DuplicateName
from app.modules.clientes.application.versioning import version_tag
from app.modules.clientes.domain.rules import (
    ClientRuleError,
    ensure_deletable,
    ensure_editable_fields,
    ensure_restorable,
    ensure_vigente_state,
    normalize_fields,
)


def _fingerprint(query: str, state: str, sector: str) -> str:
    return hashlib.sha256(json.dumps([query, state, sector], ensure_ascii=False).encode()).hexdigest()[:16]


def _decode_cursor(cursor: str, fingerprint: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        marker, value = raw.split(":", 1)
        if marker != fingerprint or int(value) < 0:
            raise ValueError
        return int(value)
    except (ValueError, UnicodeError, binascii.Error):
        raise ClientProblem(ProblemKind.VALIDATION, "Cursor inválido para estos filtros") from None


class ClientUseCases:
    def __init__(self, uow: ClientUnitOfWork):
        self.uow = uow

    def list(self, query: str, state: str, order: str | None, sector: str, cursor: str | None, limit: int) -> dict[str, Any]:
        if order is not None:
            raise ClientProblem(ProblemKind.VALIDATION, "El contrato aún no define valores para orden")
        query, sector = query.strip(), sector.strip()
        fingerprint = _fingerprint(query, state, sector)
        after_id = _decode_cursor(cursor, fingerprint) if cursor else None
        total, rows = self.uow.clients.list(query, state, sector, after_id, limit + 1)
        items = rows[:limit]
        following = None
        if len(rows) > limit:
            following = base64.urlsafe_b64encode(f"{fingerprint}:{items[-1]['id']}".encode()).decode().rstrip("=")
        return {"items": items, "siguiente": following, "total_aprox": total}

    def sectors(self) -> dict[str, list[str]]:
        return {"items": self.uow.clients.sectors()}

    def get(self, client_id: int) -> dict[str, Any]:
        row = self.uow.clients.get(client_id)
        if row is None:
            raise ClientProblem(ProblemKind.NOT_FOUND, "Cliente no encontrado")
        return row

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        try:
            values = normalize_fields(values)
            ensure_vigente_state(values["estado_id"])
        except ClientRuleError as exc:
            raise ClientProblem(ProblemKind.VALIDATION, str(exc)) from exc
        with self.uow:
            if self.uow.clients.name_exists(values["nombre"]):
                raise ClientProblem(ProblemKind.CONFLICT, "Ya existe un cliente vigente con ese nombre")
            try:
                row = self.uow.clients.create(values, actor_id)
                self.uow.audit.record(actor_id, "crear", row)
                self.uow.commit()
            except DuplicateName:
                raise ClientProblem(ProblemKind.CONFLICT, "Ya existe un cliente vigente con ese nombre") from None
        return row

    def edit(self, client_id: int, changes: dict[str, Any], expected_version: str | None, actor_id: int) -> dict[str, Any]:
        if expected_version is None:
            raise ClientProblem(ProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        with self.uow:
            previous = self.uow.clients.get_for_update(client_id)
            if previous is None:
                raise ClientProblem(ProblemKind.NOT_FOUND, "Cliente no encontrado")
            if expected_version != version_tag(previous):
                raise ClientProblem(ProblemKind.PRECONDITION_FAILED, "El cliente cambió desde la última lectura")
            if not changes:
                return previous
            try:
                ensure_editable_fields(changes)
                changes = normalize_fields(changes)
            except ClientRuleError as exc:
                raise ClientProblem(ProblemKind.VALIDATION, str(exc)) from exc
            if "nombre" in changes and self.uow.clients.name_exists(changes["nombre"], client_id):
                raise ClientProblem(ProblemKind.CONFLICT, "Ya existe un cliente vigente con ese nombre")
            try:
                row = self.uow.clients.update(client_id, changes, actor_id)
                self.uow.audit.record(actor_id, "editar", row, previous)
                self.uow.commit()
            except DuplicateName:
                raise ClientProblem(ProblemKind.CONFLICT, "Ya existe un cliente vigente con ese nombre") from None
        return row

    def delete(self, client_id: int, actor_id: int) -> None:
        with self.uow:
            previous = self.uow.clients.get_for_update(client_id)
            if previous is None:
                raise ClientProblem(ProblemKind.NOT_FOUND, "Cliente no encontrado")
            try:
                ensure_deletable(self.uow.accounts.locked_states_for_client(client_id))
            except ClientRuleError as exc:
                raise ClientProblem(ProblemKind.CONFLICT, str(exc)) from exc
            row = self.uow.clients.soft_delete(client_id, actor_id)
            self.uow.audit.record(actor_id, "eliminar", row, previous)
            self.uow.commit()

    def restore(self, client_id: int, actor_id: int) -> dict[str, Any]:
        with self.uow:
            previous = self.uow.clients.get_for_update(client_id, include_deleted=True)
            if previous is None:
                raise ClientProblem(ProblemKind.NOT_FOUND, "Cliente no encontrado")
            try:
                ensure_restorable(previous["estado_id"])
            except ClientRuleError as exc:
                raise ClientProblem(ProblemKind.VALIDATION, str(exc)) from exc
            try:
                row = self.uow.clients.restore(client_id, actor_id)
                self.uow.audit.record(actor_id, "restaurar", row, previous)
                self.uow.commit()
            except DuplicateName:
                raise ClientProblem(ProblemKind.VALIDATION, "Ya existe un cliente vigente con ese nombre; no se restauró") from None
        return row

    def change_state(self, client_id: int, state: int, actor_id: int) -> dict[str, Any]:
        try:
            ensure_vigente_state(state)
        except ClientRuleError as exc:
            raise ClientProblem(ProblemKind.VALIDATION, str(exc)) from exc
        with self.uow:
            previous = self.uow.clients.get_for_update(client_id)
            if previous is None:
                raise ClientProblem(ProblemKind.NOT_FOUND, "Cliente no encontrado")
            if previous["estado_id"] == state:
                return previous
            row = self.uow.clients.change_state(client_id, state, actor_id)
            self.uow.audit.record(actor_id, "cambio_estado", row, previous)
            self.uow.commit()
        return row
