"""Comprueba STARTTLS y autenticación SMTP sin enviar mensajes."""

from __future__ import annotations

import smtplib
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import WorkerSettings


def main() -> None:
    settings = WorkerSettings.from_environment()
    if settings.queue != "q.notificaciones" or not settings.smtp_host or not settings.smtp_user:
        raise SystemExit("Falta la configuración del worker de correo")
    if not settings.smtp_password_file.is_file():
        raise SystemExit("No aparece el archivo privado de la contraseña SMTP")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_password_file.read_text(encoding="utf-8").strip())
            server.noop()
    except smtplib.SMTPAuthenticationError:
        raise SystemExit("El proveedor rechazó la autenticación SMTP") from None
    except (OSError, smtplib.SMTPException):
        raise SystemExit("Falló la conexión TLS o la respuesta del proveedor SMTP") from None
    print("STARTTLS y autenticación SMTP verificados; no se envió correo.")


if __name__ == "__main__":
    main()
