"""Archivos privados locales; la aplicación solo conoce la interfaz ObjectStore."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
from typing import AsyncIterable
from uuid import uuid4


KEY_PATTERN = re.compile(r"[1-9][0-9]*/[1-9][0-9]*/[0-9a-f]{32}(?:-[0-9a-f]{64})?\.(?:csv|xlsx|xls)\Z")


def _private(path: Path) -> None:
    if os.name == "nt":
        account = os.environ.get("USERDOMAIN", "") + "\\" + os.environ["USERNAME"]
        result = subprocess.run(["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"{account}:F"],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError("No se pudo proteger el almacenamiento local")
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


class LocalObjectStore:
    def __init__(self, root: Path):
        root = root.expanduser()
        if not root.is_absolute() or root.is_symlink():
            raise ValueError("SYNTRA_UPLOAD_ROOT debe ser absoluto y no un enlace")
        repository = Path(__file__).resolve().parents[5]
        if root == repository or repository in root.parents:
            raise ValueError("SYNTRA_UPLOAD_ROOT debe estar fuera del repositorio")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _private(root)
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError("Clave de archivo inválida")
        candidate = self.root.joinpath(*key.split("/"))
        if os.name == "nt":
            # Windows puede virtualizar un archivo regular bajo LocalAppData a
            # Packages/.../LocalCache al resolverlo. La clave ya tiene una
            # gramática cerrada; comprobamos contención léxica y rechazamos
            # enlaces/junctions en cada componente controlable.
            if not candidate.is_relative_to(self.root):
                raise ValueError("Clave de archivo fuera de la raíz")
            current = candidate
            while current != self.root:
                if current.is_symlink() or current.is_junction():
                    raise ValueError("Clave de archivo fuera de la raíz")
                current = current.parent
        elif not candidate.resolve().is_relative_to(self.root):
            raise ValueError("Clave de archivo fuera de la raíz")
        return candidate

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def remove(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    async def write(self, key: str, chunks: AsyncIterable[bytes], max_bytes: int) -> tuple[int, bytes]:
        destination = self.path(key)
        directory = destination.parent
        missing = []
        cursor = directory
        while cursor != self.root and not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        for item in reversed(missing):
            item.mkdir(mode=0o700)
            _private(item)
        if destination.exists():
            raise FileExistsError("El archivo ya existe")
        temporary = directory / f".{uuid4().hex}.partial"
        digest = sha256()
        total = 0
        published = False
        try:
            with temporary.open("xb") as handle:
                _private(temporary)
                async for chunk in chunks:
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("El archivo supera 50 MB")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if total == 0:
                raise ValueError("El archivo está vacío")
            os.replace(temporary, destination)
            published = True
            _private(destination)
            return total, digest.digest()
        except Exception:
            if published:
                destination.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
