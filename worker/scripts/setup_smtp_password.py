r"""Guarda la contraseña de aplicación SMTP fuera del repositorio.

Uso desde CMD: ..\backend\.venv\Scripts\python.exe scripts\setup_smtp_password.py
La entrada se solicita sin eco; el archivo existente nunca se sobrescribe.
"""

from __future__ import annotations

from getpass import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.private_files import restrict_to_current_user


def destination() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise RuntimeError("LOCALAPPDATA no está disponible")
    return Path(base) / "Syntra" / "private" / "smtp_password"


def save_password(path: Path, password: str) -> None:
    if not password or "\n" in password or "\r" in password:
        raise ValueError("La contraseña no puede estar vacía ni contener saltos de línea")
    path.parent.mkdir(parents=True, exist_ok=True)
    restrict_to_current_user(path.parent)
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            created = True
            handle.write(password)
        restrict_to_current_user(path)
    except Exception:
        # No dejar una credencial con ACL incompleta; jamás tocar una preexistente.
        if created:
            path.unlink()
        raise


if __name__ == "__main__":
    target = destination()
    if target.exists():
        raise SystemExit("Ya existe una credencial SMTP privada; no se sobrescribe")
    secret = getpass("Nueva contraseña de aplicación SMTP (no se mostrará): ")
    try:
        save_password(target, secret)
    finally:
        secret = ""
    print(f"Credencial privada guardada en {target}; su contenido no se mostrará.")
