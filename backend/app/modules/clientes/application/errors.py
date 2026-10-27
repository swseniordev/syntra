"""Errores de aplicación sin conceptos HTTP ni dependencias de FastAPI."""

from enum import Enum


class ProblemKind(Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PRECONDITION_REQUIRED = "precondition_required"
    PRECONDITION_FAILED = "precondition_failed"


class ClientProblem(Exception):
    def __init__(self, kind: ProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
