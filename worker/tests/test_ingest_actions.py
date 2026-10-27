"""La evaluación de relevancia no condiciona la incorporación inicial."""

import pytest
from datetime import datetime, timezone

from app.domain.ingest_actions import initial_ingest_state
from app.domain.tasks import ClaimedTask
from app.infrastructure.ingest_queue import IngestQueue


@pytest.mark.parametrize(("incorporar", "relevancia", "expected"), [
    (True, False, (True, 4)),
    (True, True, (True, 0)),
    (False, False, (False, 4)),
    (False, True, (False, 0)),
])
def test_initial_ingest_state_all_option_combinations(incorporar, relevancia, expected):
    assert initial_ingest_state({"incorporar": incorporar, "relevancia": relevancia}) == expected


@pytest.mark.parametrize(("incorporar", "relevancia"), [
    (True, False), (True, True), (False, False), (False, True),
])
def test_new_record_state_sent_to_persistence(monkeypatch, incorporar, relevancia):
    """Ejercita save_chunk sin ejecutar SQL ni crear registros funcionales."""
    class Result:
        def __init__(self, row=None): self.row = row
        def fetchone(self): return self.row

    class Cursor:
        def __init__(self): self.batches = []
        def executemany(self, sql, rows): self.batches.append((sql, rows))

    class Connection:
        def __init__(self): self.cursors = []
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, sql, _params=None):
            if "FROM ops.politica_reintento" in sql:
                return Result({"max_intentos": 3, "backoff_base_ms": 30_000,
                               "backoff_max_ms": 120_000, "timeout_ms": 2_100_000})
            if "SELECT id FROM dat.ejecucion" in sql:
                return Result({"id": 88})
            return Result()
        def cursor(self):
            cursor = Cursor()
            self.cursors.append(cursor)
            return cursor

    connection = Connection()
    queue = object.__new__(IngestQueue)
    queue._connect = lambda: connection
    monkeypatch.setattr(queue, "_owned", lambda *_args: {"payload": {"offset": 0}})
    published = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)
    row = {"fecha_publicacion": published, "red_id": 1,
           "url": "https://example.test/uno", "url_hash": bytes(32)}
    monkeypatch.setattr(queue, "_classify_chunk", lambda *_args: ([(row, 123, 202610)], 0, []))
    task = ClaimedTask(id=1, process_id=2, attempts=1, payload={"offset": 0})
    queue.save_chunk(task, "ensayo", [row], [], 1, {
        "cuenta_id": 3, "medicion_id": 4, "origin_id": 5, "archivo_id": 6,
        "options": {"incorporar": incorporar, "relevancia": relevancia},
    })
    batches = [batch for cursor in connection.cursors for batch in cursor.batches]
    assert any("INSERT INTO dat.registro(" in sql for sql, _rows in batches)
    state_sql, state_rows = next((sql, rows) for sql, rows in batches
                                 if "INSERT INTO dat.registro_estado(" in sql)
    assert "CASE WHEN %s THEN now() ELSE NULL END" in state_sql
    assert state_rows[0][4:7] == (incorporar, incorporar, 0 if relevancia else 4)
