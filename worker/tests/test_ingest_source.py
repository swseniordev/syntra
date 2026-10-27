"""Los objetos locales solo se leen dentro de la raíz privada y con hash válido."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from app.infrastructure.ingest_source import LocalIngestSource


def test_local_source_rejects_changed_content_and_path_escape(tmp_path):
    root = tmp_path / 'private'
    root.mkdir()
    directory = root / '7' / '3'
    directory.mkdir(parents=True)
    key = '7/3/' + 'a' * 32 + '.csv'
    file = directory / ('a' * 32 + '.csv')
    content = b'url,published\nhttps://example.test,2026-10-23 10:00\n'
    file.write_bytes(content)
    source = LocalIngestSource(root)
    source.verify(key, hashlib.sha256(content).digest())
    file.write_bytes(content + b'changed')
    with pytest.raises(ValueError, match='ya no coincide'):
        source.verify(key, hashlib.sha256(content).digest())
    outside = tmp_path / 'outside.csv'
    outside.write_bytes(content)
    with pytest.raises(ValueError, match='Archivo privado'):
        source.verify('../outside.csv', hashlib.sha256(content).digest())
    with pytest.raises(ValueError, match='Archivo privado'):
        source.verify('7/3/otro.csv', hashlib.sha256(content).digest())


@pytest.mark.skipif(os.name != 'nt', reason='La virtualización de LocalAppData es propia de Windows')
def test_windows_source_accepts_virtualized_regular_file_but_rejects_link(tmp_path, monkeypatch):
    root = tmp_path / 'private'
    (root / '7' / '3').mkdir(parents=True)
    key = '7/3/' + 'a' * 32 + '.csv'
    file = root / '7' / '3' / ('a' * 32 + '.csv')
    file.write_bytes(b'contenido')
    source = LocalIngestSource(root)
    original_resolve = Path.resolve
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'resolve', lambda path, *a, **kw:
                      tmp_path / 'virtualized' if path == file
                      else original_resolve(path, *a, **kw))
        source.verify(key, hashlib.sha256(b'contenido').digest())
    original_is_symlink = Path.is_symlink
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'is_symlink', lambda path:
                      path == file or original_is_symlink(path))
        with pytest.raises(ValueError, match='Archivo privado'):
            source.verify(key, hashlib.sha256(b'contenido').digest())
