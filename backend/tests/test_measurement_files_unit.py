"""Reglas de archivos y almacenamiento sin PostgreSQL ni datos funcionales."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import tempfile

import pytest

from app.modules.mediciones.application.file_service import FileProblem, MeasurementFileUseCases
from app.modules.mediciones.infrastructure.local_storage import LocalObjectStore


class FakeRepository:
    def __init__(self):
        self.measurement = {"id": 3, "cuenta_id": 7, "estado_id": 1}
        self.format = {"id": "talkwalker_simple", "mapeado": True, "extensiones": ["csv", "xlsx"]}
        self.source_active = True
        self.rows = {}
        self.commits = 0
        self.rollbacks = 0

    def visible_measurement(self, _id, actor, _global):
        return self.measurement if actor == 11 else None

    def active_format(self, _id):
        return self.format

    def file_source_active(self, _measurement_id):
        return self.source_active

    def insert_file(self, mid, name, fmt, key, size, actor):
        row = {"id": 5, "medicion_id": mid, "nombre": name, "formato_id": fmt,
               "s3_bucket": "local", "s3_key": key, "tamano_bytes": size,
               "sha256": None, "estado": "subido", "subido_en": datetime.now(timezone.utc),
               "cuenta_id": 7}
        self.rows[5] = row
        return row

    def locked_file(self, file_id, actor, _global):
        return self.rows.get(file_id) if actor == 11 else None

    def file(self, file_id, actor, _global):
        return self.locked_file(file_id, actor, _global)

    def finish_upload(self, file_id, size, digest):
        self.rows[file_id].update(tamano_bytes=size, sha256=digest)

    def duplicate_file(self, _measurement_id, _digest, _exclude_id=None):
        return None

    def list_files(self, _id, _limit):
        return list(self.rows.values())

    def enqueue(self, measurement, file_ids, actor, key, options, mode="upsert"):
        self.enqueued_mode = mode
        return {"proceso_id": 31, "estado": "en_cola"}

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


async def _chunks(*values):
    for value in values:
        yield value


def test_reservation_rejects_unmapped_format_and_cross_account_actor():
    with tempfile.TemporaryDirectory() as folder:
        repo = FakeRepository()
        cases = MeasurementFileUseCases(repo, LocalObjectStore(Path(folder)))
        repo.format["mapeado"] = False
        with pytest.raises(FileProblem, match="mapeo"):
            cases.reserve(3, "export.csv", 12, "meltwater", 11, False)
        repo.format["mapeado"] = True
        with pytest.raises(FileProblem, match="Medición no encontrada"):
            cases.reserve(3, "export.csv", 12, "talkwalker_simple", 12, False)
        with pytest.raises(FileProblem, match="Nombre de archivo inválido"):
            cases.reserve(3, "../export.csv", 12, "talkwalker_simple", 11, False)


def test_reservation_rejects_inactive_file_source_before_creating_file():
    with tempfile.TemporaryDirectory() as folder:
        repo = FakeRepository()
        repo.source_active = False
        cases = MeasurementFileUseCases(repo, LocalObjectStore(Path(folder)))
        with pytest.raises(FileProblem, match="fuente de archivos no está activa") as error:
            cases.reserve(3, "export.csv", 12, "talkwalker_simple", 11, False)
        assert error.value.status == 409
        assert repo.rows == {}


def test_duplicate_digest_reuses_existing_reference_without_reservation():
    with tempfile.TemporaryDirectory() as folder:
        repo = FakeRepository()
        repo.duplicate_file = lambda _mid, _digest: {
            "archivo_id": 9, "proceso_id": 31,
            "archivo_estado": "procesado", "proceso_estado": "completado",
        }
        cases = MeasurementFileUseCases(repo, LocalObjectStore(Path(folder)))
        with pytest.raises(FileProblem) as error:
            cases.reserve(3, "copia.csv", 7, "talkwalker_simple", 11, False,
                          sha256(b"abcdefg").hexdigest())
        assert error.value.status == 409
        assert error.value.detail["archivo_id"] == 9
        assert error.value.detail["proceso_id"] == 31
        assert repo.rows == {}


def test_upload_stream_persists_digest_and_prevents_cross_account_access():
    with tempfile.TemporaryDirectory() as folder:
        repo = FakeRepository()
        store = LocalObjectStore(Path(folder))
        cases = MeasurementFileUseCases(repo, store)
        result = cases.reserve(3, "export.csv", 7, "talkwalker_simple", 11, False)
        assert result["archivo_id"] == 5
        with pytest.raises(FileProblem, match="Archivo no encontrado"):
            asyncio.run(cases.upload(5, _chunks(b"abc"), 12, False))
        asyncio.run(cases.upload(5, _chunks(b"abc", b"defg"), 11, False))
        assert repo.rows[5]["sha256"] == sha256(b"abcdefg").digest()
        assert store.path(repo.rows[5]["s3_key"]).read_bytes() == b"abcdefg"
        assert cases.enqueue(3, [5], 11, False, "test-idempotency-key-123") == {
            "proceso_id": 31, "estado": "en_cola"}
        assert repo.enqueued_mode == "upsert"
        assert cases.enqueue(3, [5], 11, False, "test-idempotency-key-789",
                             None, "reemplazar")["proceso_id"] == 31
        assert repo.enqueued_mode == "reemplazar"
        with pytest.raises(FileProblem, match="modo de carga"):
            cases.enqueue(3, [5], 11, False, "test-idempotency-key-abc", None, "otro")
        with pytest.raises(FileProblem, match="Medición no encontrada"):
            cases.enqueue(3, [5], 12, False, "test-idempotency-key-456")


def test_wrong_size_removes_new_file_and_does_not_commit_metadata():
    with tempfile.TemporaryDirectory() as folder:
        repo = FakeRepository()
        store = LocalObjectStore(Path(folder))
        cases = MeasurementFileUseCases(repo, store)
        cases.reserve(3, "export.csv", 8, "talkwalker_simple", 11, False)
        with pytest.raises(FileProblem, match="tamaño"):
            asyncio.run(cases.upload(5, _chunks(b"abcdefg"), 11, False))
        assert not store.exists(repo.rows[5]["s3_key"])
        assert repo.rows[5]["sha256"] is None
        assert repo.rollbacks == 1


def test_local_storage_rejects_path_traversal_and_oversized_stream():
    with tempfile.TemporaryDirectory() as folder:
        store = LocalObjectStore(Path(folder))
        with pytest.raises(ValueError, match="Clave"):
            store.path("../private.txt")
        key = "7/3/" + "a" * 32 + ".csv"
        with pytest.raises(ValueError, match="50 MB"):
            asyncio.run(store.write(key, _chunks(b"12345"), 4))
        assert not store.exists(key)


@pytest.mark.skipif(os.name != "nt", reason="La virtualización de LocalAppData es propia de Windows")
def test_windows_storage_accepts_virtualized_regular_file_but_rejects_link(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        store = LocalObjectStore(Path(folder))
        key = "7/3/" + "a" * 32 + ".csv"
        candidate = store.root / "7" / "3" / ("a" * 32 + ".csv")
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes(b"csv")
        original_resolve = Path.resolve
        with monkeypatch.context() as patch:
            patch.setattr(Path, "resolve", lambda path, *a, **kw:
                          Path(folder).parent / "virtualized" if path == candidate
                          else original_resolve(path, *a, **kw))
            assert store.exists(key)
        original_is_symlink = Path.is_symlink
        with monkeypatch.context() as patch:
            patch.setattr(Path, "is_symlink", lambda path:
                          path == candidate or original_is_symlink(path))
            with pytest.raises(ValueError, match="fuera de la raíz"):
                store.path(key)
