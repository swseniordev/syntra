"""Configuración externa del worker de correo, sin secretos en el repositorio."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class WorkerSettings:
    concurrency: int
    log_level: str
    queue: str
    database_host: str
    database_port: int
    database_name: str
    database_user: str
    database_passfile: Path
    poll_seconds: float
    lease_seconds: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password_file: Path
    smtp_from: str
    mail_template_file: Path | None
    report_root: Path
    upload_root: Path

    @classmethod
    def from_environment(cls) -> "WorkerSettings":
        raw = os.getenv("SYNTRA_WORKER_CONCURRENCY")
        if raw is None:
            raise ValueError("SYNTRA_WORKER_CONCURRENCY es obligatorio y debe configurarse externamente")
        try:
            concurrency = int(raw)
        except ValueError as exc:
            raise ValueError("SYNTRA_WORKER_CONCURRENCY debe ser un entero positivo") from exc
        if not 1 <= concurrency <= 32:
            raise ValueError("SYNTRA_WORKER_CONCURRENCY debe estar entre 1 y 32")
        log_level = os.getenv("SYNTRA_LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("SYNTRA_LOG_LEVEL debe ser un nivel estándar de logging")
        queue = os.getenv("SYNTRA_WORKER_QUEUE", "q.notificaciones")
        roles = {
            "q.notificaciones": "syntra_mail_worker_login",
            "q.reportes": "syntra_report_worker_login",
            "q.mantenimiento": "syntra_measurement_worker_login",
            "q.ingesta": "syntra_ingest_worker_login",
        }
        if queue not in roles:
            raise ValueError("SYNTRA_WORKER_QUEUE no corresponde a un consumidor configurado")
        user = os.getenv("SYNTRA_WORKER_DB_USER", roles[queue])
        if user != roles[queue]:
            raise ValueError("La identidad PostgreSQL no corresponde a la cola del worker")
        poll = float(os.getenv("SYNTRA_WORKER_POLL_SECONDS", "2"))
        lease = int(os.getenv("SYNTRA_WORKER_LEASE_SECONDS", "900" if queue == "q.reportes" else "90"))
        if poll <= 0 or poll > 60 or lease < 30 or lease > 3600:
            raise ValueError("Sondeo o plazo de recuperación inválido")
        return cls(
            concurrency=concurrency, log_level=log_level, queue=queue,
            database_host=os.getenv("SYNTRA_DB_HOST", "127.0.0.1"),
            database_port=int(os.getenv("SYNTRA_DB_PORT", "5432")),
            database_name=os.getenv("SYNTRA_DB_NAME", "syntra_dev"),
            database_user=user,
            database_passfile=Path(os.getenv("SYNTRA_WORKER_DB_PASSFILE", str(
                Path(os.getenv("APPDATA", ".")) / "postgresql" / {
                    "q.reportes": "syntra_report_pgpass.conf",
                    "q.notificaciones": "syntra_mail_pgpass.conf",
                    "q.mantenimiento": "syntra_measurement_pgpass.conf",
                    "q.ingesta": "syntra_ingest_pgpass.conf",
                }[queue]))),
            poll_seconds=poll, lease_seconds=lease,
            smtp_host=os.getenv("SYNTRA_SMTP_HOST", ""),
            smtp_port=int(os.getenv("SYNTRA_SMTP_PORT", "587")),
            smtp_user=os.getenv("SYNTRA_SMTP_USER", ""),
            smtp_password_file=Path(os.getenv("SYNTRA_SMTP_PASSWORD_FILE", "")),
            smtp_from=os.getenv("SYNTRA_SMTP_FROM", ""),
            mail_template_file=Path(os.getenv("SYNTRA_MAIL_TEMPLATE_FILE", str(Path(__file__).resolve().parents[1] / "mail_template.json"))),
            report_root=Path(os.getenv("SYNTRA_REPORT_ROOT", str(Path(os.getenv("LOCALAPPDATA", ".")) / "Syntra" / "private" / "auditoria"))),
            upload_root=Path(os.getenv("SYNTRA_UPLOAD_ROOT", str(Path(os.getenv("LOCALAPPDATA", ".")) / "Syntra" / "private" / "ingesta"))),
        )
