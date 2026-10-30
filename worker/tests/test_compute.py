"""Cómputo por registro (q.llm): reglas puras y caso de uso sin PostgreSQL."""

import pytest

from app.application.compute_records import ComputeRecords
from app.domain.compute import (
    EMBEDDING,
    OK,
    PENDIENTE,
    RELEVANCIA,
    SENTIMIENTO,
    embedding_vigente,
    pasos_pendientes,
    relevancia_valida,
    sentimiento_valido,
    texto_fingerprint,
)
from app.domain.tasks import ClaimedTask


def test_texto_fingerprint_es_estable_y_sensible_al_texto():
    assert texto_fingerprint("hola") == texto_fingerprint(" hola ")
    assert texto_fingerprint("hola") != texto_fingerprint("adios")


def test_embedding_solo_vigente_si_el_texto_no_cambio():
    h = texto_fingerprint("hola")
    assert embedding_vigente(h, h)
    assert not embedding_vigente(None, h)
    assert not embedding_vigente(texto_fingerprint("otro"), h)


def test_pasos_pendientes_filtra_por_estado():
    estados = {"st_relevancia": PENDIENTE, "st_sentimiento": OK, "st_embedding": PENDIENTE}
    assert pasos_pendientes(estados) == (RELEVANCIA, EMBEDDING)


def test_dominios_de_relevancia_y_sentimiento():
    assert relevancia_valida(1) and relevancia_valida(2)
    assert not relevancia_valida(0)
    assert all(sentimiento_valido(v) for v in (-1, 0, 1))
    assert not sentimiento_valido(2)


class FakeProvider:
    def __init__(self, falla=None):
        self.falla = falla or set()

    def relevance(self, texto, prompt, timeout_s):
        if RELEVANCIA in self.falla:
            raise RuntimeError("proveedor no disponible")
        return (1, 80)

    def sentiment(self, texto, prompt, timeout_s):
        if SENTIMIENTO in self.falla:
            raise RuntimeError("proveedor no disponible")
        return 1

    def embedding(self, texto, timeout_s):
        if EMBEDDING in self.falla:
            raise RuntimeError("proveedor no disponible")
        return [0.0] * 4


class FakePersistence:
    def __init__(self, job):
        self._job = job
        self.saved = []
        self.finished = False

    def job(self, task, worker_id):
        return self._job

    def save_record(self, task, worker_id, record, resultados, problemas):
        self.saved.append((record["registro_id"], resultados, problemas))

    def finish(self, task, worker_id):
        self.finished = True


def _job(records, budget=5.0):
    return {"prompt_relevancia": "p", "prompt_sentimiento": "p",
            "timeout_paso_s": budget, "records": records}


def _record(rid, estados, texto="t", texto_hash=None):
    return {"registro_id": rid, "periodo": 202610, "texto": texto,
            "texto_hash": texto_hash, "estados": estados}


def test_calcula_solo_pasos_pendientes_y_cierra_el_lote():
    estados = {"st_relevancia": PENDIENTE, "st_sentimiento": OK, "st_embedding": PENDIENTE}
    persistence = FakePersistence(_job([_record(1, estados)]))
    ComputeRecords(persistence, FakeProvider()).execute(ClaimedTask(1, 2, 1, {}), "w", 60000)
    _, resultados, problemas = persistence.saved[0]
    assert set(resultados) == {RELEVANCIA, EMBEDDING}
    assert resultados[RELEVANCIA] == (1, 80)
    assert problemas == []
    assert persistence.finished


def test_embedding_se_reutiliza_cuando_el_texto_no_cambio():
    h = texto_fingerprint("mismo")
    estados = {"st_relevancia": OK, "st_sentimiento": OK, "st_embedding": PENDIENTE}
    persistence = FakePersistence(_job([_record(7, estados, "mismo", h)]))
    ComputeRecords(persistence, FakeProvider()).execute(ClaimedTask(1, 2, 1, {}), "w", 60000)
    _, resultados, _ = persistence.saved[0]
    assert resultados[EMBEDDING][0] == "reutilizado"


def test_un_paso_fallido_no_tumba_el_resto_del_registro():
    estados = {"st_relevancia": PENDIENTE, "st_sentimiento": PENDIENTE, "st_embedding": OK}
    persistence = FakePersistence(_job([_record(3, estados)]))
    ComputeRecords(persistence, FakeProvider(falla={SENTIMIENTO})).execute(ClaimedTask(1, 2, 1, {}), "w", 60000)
    _, resultados, problemas = persistence.saved[0]
    assert RELEVANCIA in resultados
    assert [p for p, _ in problemas] == [SENTIMIENTO]


def test_valor_fuera_de_dominio_se_registra_como_problema():
    class Loco(FakeProvider):
        def sentiment(self, texto, prompt, timeout_s):
            return 9

    estados = {"st_relevancia": OK, "st_sentimiento": PENDIENTE, "st_embedding": OK}
    persistence = FakePersistence(_job([_record(5, estados)]))
    ComputeRecords(persistence, Loco()).execute(ClaimedTask(1, 2, 1, {}), "w", 60000)
    _, resultados, problemas = persistence.saved[0]
    assert SENTIMIENTO not in resultados
    assert [p for p, _ in problemas] == [SENTIMIENTO]


def test_el_presupuesto_del_lote_corta_con_timeout():
    estados = {"st_relevancia": PENDIENTE, "st_sentimiento": OK, "st_embedding": OK}
    persistence = FakePersistence(_job([_record(1, estados), _record(2, estados)]))
    reloj = iter((0.0, 0.0, 10.0))  # execute lee el inicio y luego cada registro
    with pytest.raises(TimeoutError):
        ComputeRecords(persistence, FakeProvider(),
                       clock=lambda: next(reloj)).execute(ClaimedTask(1, 2, 1, {}), "w", 5000)
    assert len(persistence.saved) == 1  # el primero se guardó; el lote se corta antes del segundo
