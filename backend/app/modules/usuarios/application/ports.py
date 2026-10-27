"""Contrato de lectura de usuarios, independiente de PostgreSQL."""

from __future__ import annotations

from typing import Any, Protocol

User = dict[str, Any]


class UserReader(Protocol):
    def list(self, query: str, state: str, role_id: int | None, after_id: int | None, limit: int) -> tuple[int, list[User]]: ...
    def get(self, user_id: int) -> User | None: ...
