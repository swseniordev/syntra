"""Casos de uso de Cuentas con visibilidad, ETag y aprovisionamiento atómico."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from enum import Enum
from typing import Any

from app.modules.cuentas.application.ports import AccountUnitOfWork, DuplicateAccount, ProvisioningBusy
from app.modules.cuentas.domain.rules import InvalidAccount, normalize


class AccountProblemKind(Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class AccountProblem(Exception):
    def __init__(self, kind: AccountProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def version_tag(row: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(row["actualizado_en"].isoformat().encode()).hexdigest() + '"'


def _fingerprint(query: str, state: str, client_id: int | None) -> str:
    return hashlib.sha256(json.dumps([query, state, client_id], ensure_ascii=False).encode()).hexdigest()[:16]


def _after(cursor: str, fingerprint: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        marker, row_id = raw.split(":", 1)
        if marker != fingerprint or int(row_id) < 0:
            raise ValueError
        return int(row_id)
    except (UnicodeError, ValueError, binascii.Error):
        raise AccountProblem(AccountProblemKind.VALIDATION, "Cursor inválido para estos filtros") from None


class AccountUseCases:
    def __init__(self, uow: AccountUnitOfWork, *, attempts: int = 3, backoff_ms: int = 150):
        self.uow = uow
        self.attempts = attempts
        self.backoff_ms = backoff_ms

    def list(self, query: str, state: str, order: str | None, client_id: int | None,
             cursor: str | None, limit: int, actor_id: int, global_access: bool) -> dict[str, Any]:
        if order is not None:
            raise AccountProblem(AccountProblemKind.VALIDATION, "El contrato aún no define valores para orden")
        query = query.strip()
        fingerprint = _fingerprint(query, state, client_id)
        after_id = _after(cursor, fingerprint) if cursor else None
        total, rows = self.uow.accounts.list(query, state, client_id, after_id, limit + 1, actor_id, global_access)
        items = rows[:limit]
        following = None
        if len(rows) > limit:
            following = base64.urlsafe_b64encode(f"{fingerprint}:{items[-1]['id']}".encode()).decode().rstrip("=")
        return {"items": items, "siguiente": following, "total_aprox": total}

    def get(self, account_id: int, actor_id: int, global_access: bool) -> dict[str, Any]:
        row = self.uow.accounts.get(account_id, actor_id, global_access)
        if row is None:
            raise AccountProblem(AccountProblemKind.NOT_FOUND, "Cuenta no encontrada")
        return row

    def _normalize(self, values: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return normalize(values, current)
        except InvalidAccount as exc:
            raise AccountProblem(AccountProblemKind.VALIDATION, str(exc)) from exc

    def _active_client(self, client_id: int) -> None:
        if self.uow.accounts.client_state(client_id) != 1:
            raise AccountProblem(AccountProblemKind.VALIDATION, "Seleccione un cliente activo")

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        values = self._normalize(values)
        for attempt in range(self.attempts):
            try:
                with self.uow:
                    self._active_client(values["cliente_id"])
                    if self.uow.accounts.name_exists(values["nombre"]):
                        raise AccountProblem(AccountProblemKind.CONFLICT, "Ya existe una cuenta vigente con ese nombre")
                    try:
                        row = self.uow.accounts.create(values, actor_id)
                    except DuplicateAccount:
                        raise AccountProblem(AccountProblemKind.CONFLICT, "Ya existe una cuenta vigente con ese nombre") from None
                    self.uow.accounts.provision(row["id"], actor_id)
                    self._audit("crear", actor_id, row, after=row)
                    self.uow.commit()
                return row
            except ProvisioningBusy:
                if attempt == self.attempts - 1:
                    raise AccountProblem(AccountProblemKind.CONFLICT, "Aprovisionamiento ocupado; inténtelo de nuevo") from None
                time.sleep(self.backoff_ms * (2 ** attempt) / 1000)
        raise AssertionError("Se agotaron los intentos de aprovisionamiento")

    def edit(self, account_id: int, changes: dict[str, Any], expected: str | None,
             actor_id: int, global_access: bool) -> dict[str, Any]:
        if expected is None:
            raise AccountProblem(AccountProblemKind.PRECONDITION_REQUIRED, "Se requiere If-Match")
        with self.uow:
            before = self.uow.accounts.get(account_id, actor_id, global_access, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise AccountProblem(AccountProblemKind.NOT_FOUND, "Cuenta no encontrada")
            if version_tag(before) != expected:
                raise AccountProblem(AccountProblemKind.PRECONDITION_FAILED, "La cuenta cambió desde la última lectura")
            if not changes:
                return before
            changes = self._normalize(changes, before)
            if "cliente_id" in changes:
                self._active_client(changes["cliente_id"])
            if "nombre" in changes and self.uow.accounts.name_exists(changes["nombre"], account_id):
                raise AccountProblem(AccountProblemKind.CONFLICT, "Ya existe una cuenta vigente con ese nombre")
            try:
                row = self.uow.accounts.update(account_id, changes, actor_id)
            except DuplicateAccount:
                raise AccountProblem(AccountProblemKind.CONFLICT, "Ya existe una cuenta vigente con ese nombre") from None
            self._audit("editar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def delete(self, account_id: int, actor_id: int, global_access: bool) -> None:
        with self.uow:
            before = self.uow.accounts.get(account_id, actor_id, global_access, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise AccountProblem(AccountProblemKind.NOT_FOUND, "Cuenta no encontrada")
            row = self.uow.accounts.update(account_id, {"estado_id": -1}, actor_id)
            self._audit("eliminar", actor_id, row, before=before, after=row)
            self.uow.commit()

    def restore(self, account_id: int, actor_id: int, global_access: bool) -> dict[str, Any]:
        with self.uow:
            before = self.uow.accounts.get(account_id, actor_id, global_access, for_update=True)
            if before is None:
                raise AccountProblem(AccountProblemKind.NOT_FOUND, "Cuenta no encontrada")
            if before["estado_id"] != -1:
                raise AccountProblem(AccountProblemKind.VALIDATION, "La cuenta no está eliminada")
            if self.uow.accounts.name_exists(before["nombre"], account_id):
                raise AccountProblem(AccountProblemKind.CONFLICT, "Ya existe una cuenta vigente con ese nombre")
            try:
                row = self.uow.accounts.update(account_id, {"estado_id": 0}, actor_id)
            except DuplicateAccount:
                raise AccountProblem(AccountProblemKind.CONFLICT, "Ya existe una cuenta vigente con ese nombre") from None
            self._audit("restaurar", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def change_state(self, account_id: int, state: int, actor_id: int, global_access: bool) -> dict[str, Any]:
        with self.uow:
            before = self.uow.accounts.get(account_id, actor_id, global_access, for_update=True)
            if before is None or before["estado_id"] == -1:
                raise AccountProblem(AccountProblemKind.NOT_FOUND, "Cuenta no encontrada")
            if before["estado_id"] == state:
                return before
            row = self.uow.accounts.update(account_id, {"estado_id": state}, actor_id)
            self._audit("cambio_estado", actor_id, row, before=before, after=row)
            self.uow.commit()
        return row

    def _audit(self, action: str, actor_id: int, row: dict[str, Any], **values: Any) -> None:
        self.uow.audit.record(actor_id=actor_id, module="cuentas", action=action,
                              entity_type="Cuenta", entity_id=str(row["id"]), entity_name=row["nombre"], **values)
