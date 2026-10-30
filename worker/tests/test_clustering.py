"""Clustering jerárquico puro y corrida de análisis sin PostgreSQL."""

import numpy as np

from app.application.run_analysis import RunAnalysis
from app.domain.clustering import hierarchical, kmeans, parse_vector, summarize_clusters


def test_parse_vector_lee_literal_halfvec():
    assert parse_vector("[1,2,3]") == [1.0, 2.0, 3.0]
    assert parse_vector("[ -0.5, 0.25 ]") == [-0.5, 0.25]
    assert parse_vector("[]") == []
    assert parse_vector("") == []


def test_kmeans_separa_dos_nubes_evidentes():
    x = np.array([[0.0, 0.0], [0.1, 0.1], [10.0, 10.0], [10.1, 9.9]])
    labels = kmeans(x, 2, seed=0)
    assert labels[0] == labels[1]      # las dos cercanas al origen juntas
    assert labels[2] == labels[3]      # las dos lejanas juntas
    assert labels[0] != labels[2]


def test_kmeans_recorta_k_al_numero_de_muestras():
    x = np.array([[0.0], [1.0]])
    labels = kmeans(x, 10, seed=0)
    assert set(labels.tolist()) <= {0, 1}
    assert kmeans(np.empty((0, 3)), 5).shape == (0,)


def test_hierarchical_devuelve_cluster_y_subcluster_por_fila():
    x = np.array([[0.0, 0.0], [0.2, 0.0], [9.0, 9.0], [9.2, 9.1]])
    labels, subs = hierarchical(x, 2, 2, seed=0)
    assert labels.shape == (4,) and subs.shape == (4,)


def test_summarize_clusters_conteos_y_orden():
    labels = np.array([0, 0, 1])
    subs = np.array([0, 1, 0])
    arbol = summarize_clusters(labels, subs)
    assert [c["orden"] for c in arbol] == [0, 1]
    assert sum(c["registros"] for c in arbol) == 3
    primero = arbol[0]
    assert primero["registros"] == 2
    assert {s["idx"] for s in primero["subs"]} == {0, 1}


class FakePort:
    def __init__(self, config, filas):
        self._config = config
        self._filas = filas
        self.corrida = None
        self.assigned = None
        self.activated = None

    def config(self, proceso_id):
        return self._config

    def embeddings(self, cuenta_id, medicion_id, modelo_id):
        return self._filas

    def create_corrida(self, config, registros):
        self.corrida = (config, registros)
        return 55

    def save_clusters(self, corrida_id, arbol):
        cluster_map = {c["idx"]: 100 + c["idx"] for c in arbol}
        sub_map = {(c["idx"], s["idx"]): 200 + c["idx"] * 10 + s["idx"]
                   for c in arbol for s in c["subs"]}
        return cluster_map, sub_map

    def assign(self, corrida_id, cuenta_id, medicion_id, asignaciones):
        self.assigned = (corrida_id, asignaciones)

    def activate(self, corrida_id, medicion_id):
        self.activated = corrida_id


def _config():
    return {"medicion_id": 4, "cuenta_id": 3, "k": 2, "k_sub": 2, "precluster": False,
            "modelo_embedding_id": 9}


def _filas():
    nubes = [[0.0, 0.0], [0.1, 0.0], [9.0, 9.0], [9.1, 9.0]]
    return [{"periodo": 202610, "registro_id": i + 1, "vector": v} for i, v in enumerate(nubes)]


def test_sin_config_no_corre():
    assert RunAnalysis(FakePort(None, [])).execute(7) == 0


def test_sin_embeddings_no_corre():
    assert RunAnalysis(FakePort(_config(), [])).execute(7) == 0


def test_corrida_crea_asigna_y_activa():
    port = FakePort(_config(), _filas())
    total = RunAnalysis(port).execute(7)
    assert total == 4
    assert port.corrida == (_config(), 4)
    corrida_id, asignaciones = port.assigned
    assert corrida_id == 55 and len(asignaciones) == 4
    # cada asignación referencia un cluster y subcluster del mapa
    for periodo, registro_id, cluster_id, subcluster_id in asignaciones:
        assert cluster_id in (100, 101)
        assert subcluster_id >= 200
    assert port.activated == 55
