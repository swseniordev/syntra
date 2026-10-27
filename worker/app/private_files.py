"""Permisos de archivos locales que contienen credenciales del worker."""

import os
from pathlib import Path
import subprocess


def restrict_to_current_user(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    account = os.environ.get("USERDOMAIN", "") + "\\" + os.environ["USERNAME"]
    result = subprocess.run(
        ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"{account}:F"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError("No se pudo restringir el archivo de credenciales")
