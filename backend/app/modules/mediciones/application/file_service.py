"""Casos de uso de archivos, independientes de HTTP, PostgreSQL y rutas físicas."""

from __future__ import annotations

import base64
import binascii
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
import re
from typing import Any, AsyncIterable, Protocol
from uuid import uuid4


MAX_FILE_BYTES = 50 * 1024 * 1024
UPLOAD_VALIDITY = timedelta(minutes=15)


class FileProblem(Exception):
    def __init__(self, status: int, detail: str | dict):
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


class FileRepository(Protocol):
    def visible_measurement(self, measurement_id: int, actor_id: int, global_access: bool) -> dict | None: ...
    def file_source_active(self, measurement_id: int) -> bool: ...
    def active_format(self, format_id: str) -> dict | None: ...
    def insert_file(self, measurement_id: int, name: str, format_id: str, key: str,
                    size: int, actor_id: int) -> dict: ...
    def locked_file(self, file_id: int, actor_id: int, global_access: bool) -> dict | None: ...
    def file(self, file_id: int, actor_id: int, global_access: bool) -> dict | None: ...
    def finish_upload(self, file_id: int, size: int, digest: bytes) -> dict | None: ...
    def duplicate_file(self, measurement_id: int, digest: bytes,
                       exclude_id: int | None = None) -> dict | None: ...
    def list_files(self, measurement_id: int, limit: int,
                   before: tuple[datetime, int] | None) -> list[dict]: ...
    def list_lots(self, measurement_id: int, limit: int,
                  before: tuple[datetime, int] | None, origin: str | None) -> list[dict]: ...
    def enqueue(self, measurement: dict, file_ids: list[int], actor_id: int,
                idempotency_key: str, options: dict[str, bool] | None,
                mode: str) -> dict: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class ObjectStore(Protocol):
    async def write(self, key: str, chunks: AsyncIterable[bytes], max_bytes: int) -> tuple[int, bytes]: ...
    def exists(self, key: str) -> bool: ...
    def remove(self, key: str) -> None: ...
    def path(self, key: str) -> PurePath: ...


class MeasurementFileUseCases:
    def __init__(self, repository: FileRepository, store: ObjectStore):
        self.repository = repository
        self.store = store

    def _measurement(self, measurement_id: int, actor_id: int, global_access: bool) -> dict:
        row = self.repository.visible_measurement(measurement_id, actor_id, global_access)
        if row is None:
            raise FileProblem(404, "Medición no encontrada")
        return row

    @staticmethod
    def _duplicate_problem(row: dict) -> FileProblem:
        return FileProblem(409, {"codigo": "archivo_duplicado",
                                 "archivo_id": row["archivo_id"],
                                 "proceso_id": row["proceso_id"],
                                 "estado_archivo": row["archivo_estado"],
                                 "estado_proceso": row["proceso_estado"]})

    def reserve(self, measurement_id: int, name: str, size: int, format_id: str,
                actor_id: int, global_access: bool,
                expected_sha256: str | None = None) -> dict[str, Any]:
        if not 0 < size <= MAX_FILE_BYTES:
            raise FileProblem(400, "El archivo debe pesar entre 1 byte y 50 MB")
        if (not name or len(name) > 255 or name != PurePath(name).name or '\\' in name or '/'
                in name or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise FileProblem(400, "Nombre de archivo inválido")
        suffix = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        measurement = self._measurement(measurement_id, actor_id, global_access)
        if not self.repository.file_source_active(measurement_id):
            raise FileProblem(409, "La fuente de archivos no está activa en esta medición")
        fmt = self.repository.active_format(format_id)
        if fmt is None or not fmt["mapeado"]:
            raise FileProblem(400, "El formato no tiene un mapeo activo para ingesta")
        if suffix not in fmt["extensiones"]:
            raise FileProblem(400, "La extensión no corresponde al formato seleccionado")
        if expected_sha256 is not None and not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256):
            raise FileProblem(400, 'La huella SHA-256 declarada no es válida')
        if expected_sha256 is not None:
            duplicate = self.repository.duplicate_file(measurement_id, bytes.fromhex(expected_sha256))
            if duplicate is not None:
                raise self._duplicate_problem(duplicate)
        marker = f'-{expected_sha256.lower()}' if expected_sha256 is not None else ''
        key = f"{measurement['cuenta_id']}/{measurement_id}/{uuid4().hex}{marker}.{suffix}"
        try:
            row = self.repository.insert_file(measurement_id, name, format_id, key, size, actor_id)
            self.repository.commit()
        except Exception:
            self.repository.rollback()
            raise
        return {"archivo_id": row["id"], "url": f"/api/v1/archivos/{row['id']}/contenido",
                "campos": {}, "expira_en": (row["subido_en"] + UPLOAD_VALIDITY).isoformat()}

    async def upload(self, file_id: int, chunks: AsyncIterable[bytes], actor_id: int,
                     global_access: bool) -> None:
        row = self.repository.locked_file(file_id, actor_id, global_access)
        if row is None:
            raise FileProblem(404, "Archivo no encontrado")
        if row["s3_bucket"] != "local" or row["sha256"] is not None or self.store.exists(row["s3_key"]):
            raise FileProblem(409, "El archivo ya fue cargado")
        if datetime.now(timezone.utc) > row["subido_en"] + UPLOAD_VALIDITY:
            raise FileProblem(409, "La autorización de carga venció; solicita una nueva")
        written = False
        try:
            size, digest = await self.store.write(row["s3_key"], chunks, MAX_FILE_BYTES)
            written = True
            if size != row["tamano_bytes"]:
                raise FileProblem(400, "El tamaño del archivo no coincide con el declarado")
            filename = row["s3_key"].rsplit('/', 1)[-1].rsplit('.', 1)[0]
            if '-' in filename and not hmac.compare_digest(filename.split('-', 1)[1], digest.hex()):
                raise FileProblem(400, 'La huella SHA-256 no coincide con el archivo')
            duplicate = self.repository.duplicate_file(row["medicion_id"], digest, file_id)
            if duplicate is None:
                duplicate = self.repository.finish_upload(file_id, size, digest)
            if duplicate is not None:
                raise self._duplicate_problem(duplicate)
            self.repository.commit()
        except Exception:
            self.repository.rollback()
            if written:
                self.store.remove(row["s3_key"])
            raise

    def list(self, measurement_id: int, limit: int, actor_id: int,
             global_access: bool, cursor: str | None = None) -> tuple[list[dict], str | None]:
        self._measurement(measurement_id, actor_id, global_access)
        before = None
        if cursor:
            if len(cursor) > 200:
                raise FileProblem(400, 'Cursor de archivos inválido')
            try:
                raw = base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode('ascii')
                timestamp, identifier = raw.rsplit('|', 1)
                before = (datetime.fromisoformat(timestamp), int(identifier))
                if before[0].tzinfo is None or before[1] < 1:
                    raise ValueError
            except (ValueError, UnicodeError, binascii.Error) as exc:
                raise FileProblem(400, 'Cursor de archivos inválido') from exc
        rows = self.repository.list_files(measurement_id, limit + 1, before)
        items = rows[:limit]
        next_cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            marker = f"{last['subido_en'].isoformat()}|{last['id']}".encode('ascii')
            next_cursor = base64.urlsafe_b64encode(marker).decode('ascii').rstrip('=')
        return items, next_cursor

    def lots(self, measurement_id: int, limit: int, actor_id: int,
             global_access: bool, cursor: str | None = None,
             origin: str | None = None) -> tuple[list[dict], str | None]:
        self._measurement(measurement_id, actor_id, global_access)
        before = None
        if cursor:
            if len(cursor) > 200:
                raise FileProblem(400, 'Cursor de lotes inválido')
            try:
                raw = base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode('ascii')
                timestamp, identifier = raw.rsplit('|', 1)
                before = (datetime.fromisoformat(timestamp), int(identifier))
                if before[0].tzinfo is None or before[1] < 1:
                    raise ValueError
            except (ValueError, UnicodeError, binascii.Error) as exc:
                raise FileProblem(400, 'Cursor de lotes inválido') from exc
        rows = self.repository.list_lots(measurement_id, limit + 1, before, origin)
        items = rows[:limit]
        next_cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            marker = f"{last['creado_en'].isoformat()}|{last['id']}".encode('ascii')
            next_cursor = base64.urlsafe_b64encode(marker).decode('ascii').rstrip('=')
        return items, next_cursor

    def get_download(self, file_id: int, actor_id: int, global_access: bool) -> tuple[dict, PurePath]:
        row = self.repository.file(file_id, actor_id, global_access)
        if row is None:
            raise FileProblem(404, "Archivo no encontrado")
        if row["s3_bucket"] != "local" or row["sha256"] is None or not self.store.exists(row["s3_key"]):
            raise FileProblem(404, "El contenido del archivo no está disponible")
        return row, self.store.path(row["s3_key"])

    def enqueue(self, measurement_id: int, file_ids: list[int], actor_id: int,
                global_access: bool, idempotency_key: str,
                options: dict[str, bool] | None = None,
                mode: str = "upsert") -> dict:
        if not file_ids or len(file_ids) > 100 or len(set(file_ids)) != len(file_ids):
            raise FileProblem(400, "Selecciona entre 1 y 100 archivos sin repetir")
        if not 16 <= len(idempotency_key) <= 128:
            raise FileProblem(400, "Idempotency-Key debe tener entre 16 y 128 caracteres")
        if options is not None and set(options) - {"incorporar", "relevancia", "sentimiento", "clusters", "bots"}:
            raise FileProblem(400, "Las opciones al incorporar no son válidas")
        if mode not in {"upsert", "reemplazar"}:
            raise FileProblem(400, "El modo de carga debe ser upsert o reemplazar")
        measurement = self._measurement(measurement_id, actor_id, global_access)
        for file_id in file_ids:
            row = self.repository.locked_file(file_id, actor_id, global_access)
            if (row is None or row["medicion_id"] != measurement_id or row["s3_bucket"] != "local"
                    or row["sha256"] is None or not self.store.exists(row["s3_key"])):
                raise FileProblem(400, "Uno de los archivos no pertenece a la medición o no terminó de cargarse")
        try:
            result = self.repository.enqueue(measurement, file_ids, actor_id, idempotency_key, options, mode)
            self.repository.commit()
            return result
        except Exception:
            self.repository.rollback()
            raise
