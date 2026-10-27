"""Configuración central de la API. No carga secretos ni conecta a servicios."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "Syntra API"
    environment: str = "local"
    log_level: str = "INFO"
    database_host: str = "127.0.0.1"
    database_port: int = 5432
    database_name: str = "syntra_dev"
    database_user: str = "syntra_api_login"
    jwt_private_key: Path = Path(os.getenv("LOCALAPPDATA", ".")) / "Syntra" / "keys" / "jwt-private.pem"
    database_passfile: Path = Path(os.getenv("APPDATA", ".")) / "postgresql" / "syntra_api_pgpass.conf"
    public_origin: str = "https://127.0.0.1:5173"
    report_root: Path = Path(os.getenv("LOCALAPPDATA", ".")) / "Syntra" / "private" / "auditoria"
    upload_root: Path = Path(os.getenv("LOCALAPPDATA", ".")) / "Syntra" / "private" / "ingesta"
    account_provision_attempts: int = 3
    account_provision_backoff_ms: int = 150

    @classmethod
    def from_environment(cls) -> "Settings":
        environment = os.getenv("SYNTRA_ENVIRONMENT", "local").strip().lower()
        log_level = os.getenv("SYNTRA_LOG_LEVEL", "INFO").strip().upper()
        allowed_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if not environment:
            raise ValueError("SYNTRA_ENVIRONMENT no puede estar vacío")
        if log_level not in allowed_levels:
            raise ValueError("SYNTRA_LOG_LEVEL debe ser un nivel estándar de logging")
        attempts = int(os.getenv("SYNTRA_CUENTAS_INTENTOS", "3"))
        backoff_ms = int(os.getenv("SYNTRA_CUENTAS_ESPERA_MS", "150"))
        if not 1 <= attempts <= 5 or not 0 <= backoff_ms <= 5000:
            raise ValueError("SYNTRA_CUENTAS_INTENTOS debe ser 1..5 y SYNTRA_CUENTAS_ESPERA_MS 0..5000")
        return cls(
            environment=environment,
            log_level=log_level,
            database_host=os.getenv("SYNTRA_DB_HOST", "127.0.0.1"),
            database_port=int(os.getenv("SYNTRA_DB_PORT", "5432")),
            database_name=os.getenv("SYNTRA_DB_NAME", "syntra_dev"),
            database_user=os.getenv("SYNTRA_DB_USER", "syntra_api_login"),
            jwt_private_key=Path(os.getenv("SYNTRA_JWT_PRIVATE_KEY", str(cls.jwt_private_key))),
            database_passfile=Path(os.getenv("SYNTRA_DB_PASSFILE", str(cls.database_passfile))),
            public_origin=os.getenv("SYNTRA_PUBLIC_ORIGIN", "https://127.0.0.1:5173").rstrip("/"),
            report_root=Path(os.getenv("SYNTRA_REPORT_ROOT", str(cls.report_root))),
            upload_root=Path(os.getenv("SYNTRA_UPLOAD_ROOT", str(cls.upload_root))),
            account_provision_attempts=attempts,
            account_provision_backoff_ms=backoff_ms,
        )


settings = Settings.from_environment()
