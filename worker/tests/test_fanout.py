"""Reparto a q.llm: planificación pura y caso de uso sin PostgreSQL."""

from app.application.plan_compute import PlanCompute
from app.domain.fanout import compute_proceso_tipo, fanout_needed, plan_chunks
from app.infrastructure.fanout import PostgresFanout


def test_fanout_needed_solo_si_hay_algo_que_calcular():
    assert not fanout_needed({})
    assert not fanout_needed({"incorporar": True})
    assert fanout_needed({"relevancia": True})
    assert fanout_needed({"sentimiento": True})
    assert fanout_needed({"clusters": True})


def test_compute_proceso_tipo_siempre_enruta_a_q_llm():
    assert compute_proceso_tipo({"sentimiento": True, "relevancia": True}) == "sentimiento"
    assert compute_proceso_tipo({"relevancia": True}) == "relevancia"
    # clusters-solo: embeddings se calculan en q.llm; nunca 'analisis' (esa es otra cola).
    assert compute_proceso_tipo({"clusters": True}) == "relevancia"


def test_plan_chunks_sin_registros_no_genera_ventanas():
    assert plan_chunks(202610, 1, 100, 0, 500) == []
    assert plan_chunks(202610, 100, 1, 5, 500) == []


def test_plan_chunks_una_sola_ventana_cuando_cabe():
    chunks = plan_chunks(202610, 10, 60, 40, 500)
    assert len(chunks) == 1
    assert chunks[0] == {"clave": "chunk:202610:000000", "periodo": 202610, "desde": 10, "hasta": 60}


def test_plan_chunks_cubre_el_rango_sin_huecos_ni_solapes():
    chunks = plan_chunks(202610, 1, 1000, 1000, 250)  # 4 ventanas
    assert len(chunks) == 4
    assert chunks[0]["desde"] == 1 and chunks[-1]["hasta"] == 1000
    for previo, siguiente in zip(chunks, chunks[1:]):
        assert siguiente["desde"] == previo["hasta"] + 1
    assert all(c["periodo"] == 202610 for c in chunks)
    assert len({c["clave"] for c in chunks}) == 4


class FakePort:
    def __init__(self, source, stats, child_id=10):
        self._source = source
        self._stats = stats
        self._child_id = child_id
        self.created = None
        self.enqueued = None

    def source_proceso(self, proceso_id):
        return self._source

    def pending_stats(self, cuenta_id, medicion_id, source_id):
        return self._stats

    def create_child(self, source, tipo):
        self.created = tipo
        return self._child_id

    def enqueue_chunks(self, child_id, cuenta_id, medicion_id, tipo, chunks):
        self.enqueued = (child_id, tipo, chunks)


def _source():
    return {"id": 7, "cuenta_id": 3, "medicion_id": 4, "creado_por": 2,
            "options": {"sentimiento": True}}


def test_no_reparte_si_no_hay_proceso_origen():
    port = FakePort(None, [])
    assert PlanCompute(port, 500).execute(7) == 0
    assert port.created is None


def test_no_reparte_si_no_se_pidio_calcular_nada():
    source = {**_source(), "options": {"incorporar": True}}
    port = FakePort(source, [{"periodo": 202610, "min_id": 1, "max_id": 9, "count": 9}])
    assert PlanCompute(port, 500).execute(7) == 0
    assert port.created is None and port.enqueued is None


def test_idempotente_si_el_hijo_ya_existe():
    port = FakePort(_source(), [{"periodo": 202610, "min_id": 1, "max_id": 9, "count": 9}],
                    child_id=None)
    assert PlanCompute(port, 500).execute(7) == 0
    assert port.enqueued is None  # no se encola si el reparto ya se hizo


def test_reparte_por_periodo_y_devuelve_el_numero_de_tareas():
    stats = [{"periodo": 202609, "min_id": 1, "max_id": 1000, "count": 1000},
             {"periodo": 202610, "min_id": 2001, "max_id": 2100, "count": 100}]
    port = FakePort(_source(), stats)
    total = PlanCompute(port, 250).execute(7)
    assert total == 5  # 4 ventanas en septiembre + 1 en octubre
    child_id, tipo, chunks = port.enqueued
    assert child_id == 10 and tipo == "sentimiento"
    assert {c["periodo"] for c in chunks} == {202609, 202610}


class _Result:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class _Conn:
    """Conexión fake que responde a las dos consultas de source_proceso."""
    def __init__(self, proceso, scraper=None):
        self.proceso = proceso
        self.scraper = scraper
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def execute(self, sql, params=None):
        if "FROM prc.proceso" in sql:
            return _Result(self.proceso)
        if "FROM med.scraper" in sql:
            return _Result(self.scraper)
        return _Result(None)


def test_source_proceso_de_scraper_resuelve_opciones_desde_med_scraper():
    proceso = {"id": 9, "medicion_id": 4, "cuenta_id": 3, "creado_por": None,
               "tipo": "carga_scraper", "opciones": {}, "scraper_id": 77}
    scraper = {"post_incorporar": True, "post_relevancia": False, "post_sentimiento": True,
               "post_clusters": True, "post_bots": False}
    fanout = PostgresFanout(lambda: _Conn(proceso, scraper))
    src = fanout.source_proceso(9)
    assert src["cuenta_id"] == 3 and src["medicion_id"] == 4
    # Las opciones vienen de med.scraper, no de proceso.opciones.
    assert src["options"] == {"incorporar": True, "relevancia": False, "sentimiento": True,
                              "clusters": True, "bots": False}


def test_source_proceso_de_archivo_usa_al_incorporar():
    proceso = {"id": 5, "medicion_id": 4, "cuenta_id": 3, "creado_por": 2,
               "tipo": "carga_archivo", "opciones": {"al_incorporar": {"sentimiento": True}},
               "scraper_id": None}
    fanout = PostgresFanout(lambda: _Conn(proceso))
    assert fanout.source_proceso(5)["options"] == {"sentimiento": True}
