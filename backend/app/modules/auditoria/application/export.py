"""Encolado idempotente y autorización de exportaciones de Auditoría."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Protocol


class ExportProblemKind(Enum):
    VALIDATION = "validation"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PENDING = "pending"
    GONE = "gone"


class ExportProblem(Exception):
    def __init__(self, kind: ExportProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


class ExportStore(Protocol):
    def enqueue(self, actor_id: int, key: str, filters: dict[str, Any]) -> tuple[int, bool, str]: ...
    def get(self, process_id: int) -> dict[str, Any] | None: ...


class AuditExports:
    def __init__(self, store: ExportStore):
        self.store = store

    def enqueue(self, actor_id: int, key: str | None, filters: dict[str, Any]) -> dict[str, Any]:
        if key is None or not 16 <= len(key) <= 128:
            raise ExportProblem(ExportProblemKind.VALIDATION, "Idempotency-Key debe tener entre 16 y 128 caracteres")
        for name in ("desde", "hasta"):
            value = filters.get(name)
            if value is not None and value.tzinfo is None:
                raise ExportProblem(ExportProblemKind.VALIDATION, "Las fechas deben incluir zona horaria")
        if filters.get("desde") and filters.get("hasta") and filters["desde"] > filters["hasta"]:
            raise ExportProblem(ExportProblemKind.VALIDATION, "El inicio del periodo debe ser anterior al fin")
        if filters.get("hasta") and filters["hasta"] > datetime.now(timezone.utc):
            raise ExportProblem(ExportProblemKind.VALIDATION, "El fin del periodo no puede ser futuro")
        canonical = {name: value.isoformat() if isinstance(value, datetime) else value
                     for name, value in filters.items() if value is not None and value != ""}
        dedupe = hashlib.sha256(f"auditoria:{actor_id}:{key}".encode()).hexdigest()
        process_id, compatible, state = self.store.enqueue(actor_id, dedupe, canonical)
        if not compatible:
            raise ExportProblem(ExportProblemKind.CONFLICT, "Idempotency-Key ya se usó con otros filtros")
        return {"proceso_id": process_id, "tipo": "exportacion", "estado": state}

    def owned(self, process_id: int, actor_id: int) -> dict[str, Any]:
        row = self.store.get(process_id)
        if row is None or row["tipo"] != "exportacion" or row["opciones"].get("kind") != "auditoria":
            raise ExportProblem(ExportProblemKind.NOT_FOUND, "Exportación no encontrada")
        if row["creado_por"] != actor_id:
            raise ExportProblem(ExportProblemKind.NOT_FOUND, "Exportación no encontrada")
        return row
