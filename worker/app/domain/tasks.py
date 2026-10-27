"""Datos y decisiones puras del ciclo de tareas existente."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimedTask:
    id: int
    process_id: int
    attempts: int
    payload: dict


def retry_delay_ms(attempts: int, maximum: int, base_ms: int, cap_ms: int) -> int | None:
    """None indica que se agotaron los intentos configurados."""
    if attempts >= maximum:
        return None
    return min(cap_ms, base_ms * 2 ** (attempts - 1))


def mail_user_eligible(user: dict | None, expected_version: int) -> bool:
    return bool(user and user["estado_id"] == 1 and user["version_token"] == expected_version)


@dataclass(frozen=True)
class AuditReportRequest:
    filters: dict
    cutoff: str

    @classmethod
    def from_options(cls, options: dict) -> "AuditReportRequest":
        if options.get("kind") != "auditoria" or not isinstance(options.get("filters"), dict):
            raise ValueError("Tipo de exportación inválido")
        cutoff = options.get("corte")
        if not isinstance(cutoff, str):
            raise ValueError("Corte de exportación inválido")
        return cls(options["filters"], cutoff)
