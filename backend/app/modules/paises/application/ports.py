"""Contratos que los casos de uso de Países necesitan."""

from typing import Any, Protocol, Self

from app.modules.auditoria.application.ports import AuditWriter

Country = dict[str, Any]


class DuplicateCode(Exception):
    pass


class CountryRepository(Protocol):
    def list(self, query: str, state: str, after_id: int | None, limit: int) -> tuple[int, list[Country]]: ...
    def get(self, country_id: int, *, for_update: bool = False) -> Country | None: ...
    def code_exists(self, code: str, exclude_id: int | None = None) -> bool: ...
    def create(self, values: Country, actor_id: int) -> Country: ...
    def update(self, country_id: int, values: Country, actor_id: int) -> Country: ...


class CountryUnitOfWork(Protocol):
    countries: CountryRepository
    audit: AuditWriter

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...
    def commit(self) -> None: ...
