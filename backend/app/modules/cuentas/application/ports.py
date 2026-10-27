"""Puertos de Cuentas: repositorio, aprovisionamiento y auditoría."""

from __future__ import annotations

from typing import Any, Protocol, Self

from app.modules.auditoria.application.ports import AuditWriter

Account = dict[str, Any]


class DuplicateAccount(Exception):
    pass


class ProvisioningBusy(Exception):
    pass


class AccountRepository(Protocol):
    def list(self, query: str, state: str, client_id: int | None, after_id: int | None, limit: int,
             actor_id: int, global_access: bool) -> tuple[int, list[Account]]: ...
    def get(self, account_id: int, actor_id: int, global_access: bool, *, for_update: bool = False) -> Account | None: ...
    def client_state(self, client_id: int) -> int | None: ...
    def name_exists(self, name: str, exclude_id: int | None = None) -> bool: ...
    def create(self, values: Account, actor_id: int) -> Account: ...
    def provision(self, account_id: int, actor_id: int) -> None: ...
    def update(self, account_id: int, values: Account, actor_id: int) -> Account: ...


class AccountUnitOfWork(Protocol):
    accounts: AccountRepository
    audit: AuditWriter
    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...
    def commit(self) -> None: ...
