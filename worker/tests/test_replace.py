"""Modo de carga 'reemplazar': regla pura y cierre que marca eliminado."""

from app.domain.ingest_actions import replace_mode
from app.infrastructure.ingest_queue import IngestQueue


def test_replace_mode_solo_con_modo_reemplazar():
    assert replace_mode({"modo": "reemplazar"})
    assert not replace_mode({"modo": "upsert"})
    assert not replace_mode({})
    assert not replace_mode(None)


class Result:
    def __init__(self, row=None, rowcount=0):
        self.row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, proc):
        self.proc = proc
        self.marked = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        if "FROM prc.proceso WHERE id=" in sql:
            return Result(self.proc)
        if "UPDATE dat.registro_estado e SET estado_id=-1" in sql:
            self.marked.append(params)
            return Result(rowcount=4)
        return Result()


def _run_mark(proc):
    connection = Connection(proc)
    queue = object.__new__(IngestQueue)
    queue._connect = lambda: connection
    queue._mark_replaced(7)
    return connection


def test_cierre_reemplaza_lo_no_visto_cuando_el_proceso_completo():
    proc = {"medicion_id": 4, "cuenta_id": 3, "estado": "completado",
            "opciones": {"modo": "reemplazar"}}
    connection = _run_mark(proc)
    assert connection.marked == [(3, 4, 7)]  # cuenta, medición, proceso «visto»


def test_cierre_no_reemplaza_en_modo_upsert():
    proc = {"medicion_id": 4, "cuenta_id": 3, "estado": "completado",
            "opciones": {"modo": "upsert"}}
    assert _run_mark(proc).marked == []


def test_cierre_no_reemplaza_si_el_proceso_no_termino():
    proc = {"medicion_id": 4, "cuenta_id": 3, "estado": "en_ejecucion",
            "opciones": {"modo": "reemplazar"}}
    assert _run_mark(proc).marked == []
