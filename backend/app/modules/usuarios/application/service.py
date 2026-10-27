"""Consultas de Usuarios según contrato, sin exponer credenciales."""

import base64
import binascii
import hashlib
import json
from typing import Any

from app.modules.usuarios.application.ports import UserReader


class UserQueryProblem(ValueError):
    pass


def version_tag(row: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(row["actualizado_en"].isoformat().encode()).hexdigest() + '"'


class UserQueries:
    def __init__(self, reader: UserReader):
        self.reader = reader

    def list(self, query: str, state: str, order: str | None, role_id: int | None,
             cursor: str | None, limit: int) -> dict[str, Any]:
        if order is not None:
            raise UserQueryProblem("El contrato aún no define valores para orden")
        query = query.strip()
        fingerprint = hashlib.sha256(json.dumps([query, state, role_id], ensure_ascii=False).encode()).hexdigest()[:16]
        after_id = None
        if cursor:
            try:
                raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
                marker, row_id = raw.split(":", 1)
                if marker != fingerprint or int(row_id) < 0:
                    raise ValueError
                after_id = int(row_id)
            except (UnicodeError, ValueError, binascii.Error):
                raise UserQueryProblem("Cursor inválido para estos filtros") from None
        total, rows = self.reader.list(query, state, role_id, after_id, limit + 1)
        items = rows[:limit]
        following = (base64.urlsafe_b64encode(f"{fingerprint}:{items[-1]['id']}".encode()).decode().rstrip("=")
                     if len(rows) > limit else None)
        return {"items": items, "siguiente": following, "total_aprox": total}

    def get(self, user_id: int) -> dict[str, Any] | None:
        return self.reader.get(user_id)
