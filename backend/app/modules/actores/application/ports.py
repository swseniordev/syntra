"""Contratos que los casos de uso de Actores necesitan."""

from typing import Any, Protocol, Self

from app.modules.auditoria.application.ports import AuditWriter

Actor = dict[str, Any]


class UnknownNetwork(Exception):
    pass


class ActorRepository(Protocol):
    def list(self, query: str, state: str, after_id: int | None, limit: int) -> tuple[int, list[Actor]]: ...
    def get(self, actor_id: int, *, for_update: bool = False) -> Actor | None: ...
    def create(self, values: Actor, actor_id: int) -> Actor: ...
    def update(self, actor_id: int, values: Actor, actor_id_actor: int) -> Actor: ...


class ActorUnitOfWork(Protocol):
    actors: ActorRepository
    audit: AuditWriter

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...
    def commit(self) -> None: ...
