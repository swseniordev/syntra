"""Etiquetado de clusters/temas: reglas puras y caso de uso sin PostgreSQL."""

from app.application.label_clusters import LabelClusters
from app.domain.labeling import (
    MAX_TEMAS,
    clean_label,
    sanitize_theme,
    sanitize_themes,
    valid_risk,
    valid_sentiment,
)


def test_clean_label_colapsa_y_nunca_vacio():
    assert clean_label("  Hola   mundo ") == "Hola mundo"
    assert clean_label("") == "Sin etiqueta"
    assert clean_label(None) == "Sin etiqueta"
    assert clean_label("x" * 200, max_len=10) == "x" * 10


def test_dominios_de_sentimiento_y_riesgo():
    assert all(valid_sentiment(v) for v in (-1, 0, 1))
    assert not valid_sentiment(2)
    assert valid_risk("alto") and not valid_risk("critico")


def test_sanitize_theme_liga_solo_clusters_validos():
    tema = sanitize_theme(
        {"nombre": " Economía ", "resumen": "  texto ", "sentimiento": -1,
         "riesgo": "alto", "clusters": [0, 2, 9]}, valid_ordenes=[0, 1, 2])
    assert tema["nombre"] == "Economía"
    assert tema["resumen"] == "texto"
    assert tema["sentimiento"] == -1 and tema["riesgo"] == "alto"
    assert tema["clusters"] == [0, 2]  # el 9 no existe en la corrida


def test_sanitize_theme_rechaza_tema_sin_clusters_validos():
    try:
        sanitize_theme({"nombre": "X", "clusters": [7]}, valid_ordenes=[0, 1])
        assert False, "debió lanzar ValueError"
    except ValueError:
        pass


def test_sanitize_theme_normaliza_sentimiento_y_riesgo_invalidos():
    tema = sanitize_theme({"nombre": "X", "sentimiento": 5, "riesgo": "n/a",
                           "clusters": [0]}, valid_ordenes=[0])
    assert tema["sentimiento"] is None and tema["riesgo"] is None


def test_sanitize_themes_descarta_invalidos_y_recorta_a_max():
    raws = [{"nombre": f"T{i}", "clusters": [0]} for i in range(MAX_TEMAS + 3)]
    raws.append({"nombre": "huerfano", "clusters": [99]})
    temas = sanitize_themes(raws, valid_ordenes=[0])
    assert len(temas) == MAX_TEMAS


class FakeProvider:
    def __init__(self, fail_label=False, fail_themes=False):
        self.fail_label = fail_label
        self.fail_themes = fail_themes

    def label_cluster(self, samples, prompt, timeout_s):
        if self.fail_label:
            raise RuntimeError("proveedor no disponible")
        return (f"Etiqueta {samples[0] if samples else ''}".strip(), None)

    def summarize_themes(self, clusters, prompt, timeout_s):
        if self.fail_themes:
            raise RuntimeError("proveedor no disponible")
        return [{"nombre": "General", "resumen": None, "sentimiento": 0, "riesgo": "bajo",
                 "clusters": [c["orden"] for c in clusters]}]


class FakePort:
    def __init__(self, config, clusters):
        self._config = config
        self._clusters = clusters
        self.labeled = []
        self.saved_themes = None

    def label_config(self, corrida_id):
        return self._config

    def cluster_samples(self, corrida_id, max_per_cluster):
        return self._clusters

    def save_cluster_label(self, cluster_id, nombre, descripcion):
        self.labeled.append((cluster_id, nombre))

    def save_themes(self, corrida_id, cuenta_id, medicion_id, themes, orden_to_cluster):
        self.saved_themes = (themes, orden_to_cluster)
        return len(themes)


def _config(prompt_cluster="pc", prompt_temas="pt"):
    return {"medicion_id": 4, "cuenta_id": 3, "prompt_cluster": prompt_cluster,
            "prompt_temas": prompt_temas, "timeout_paso_s": 5.0}


def _clusters():
    return [{"cluster_id": 100, "orden": 0, "nombre": "Cluster 1", "registros": 9, "samples": ["uno"]},
            {"cluster_id": 101, "orden": 1, "nombre": "Cluster 2", "registros": 4, "samples": ["dos"]}]


def test_sin_config_no_etiqueta():
    assert LabelClusters(FakePort(None, []), FakeProvider()).execute(55) == 0


def test_etiqueta_clusters_y_consolida_temas():
    port = FakePort(_config(), _clusters())
    temas = LabelClusters(port, FakeProvider()).execute(55)
    assert temas == 1
    assert [cid for cid, _ in port.labeled] == [100, 101]
    themes, orden_to_cluster = port.saved_themes
    assert orden_to_cluster == {0: 100, 1: 101}
    assert themes[0]["clusters"] == [0, 1]


def test_fallo_al_nombrar_un_cluster_no_tumba_el_resto():
    port = FakePort(_config(), _clusters())
    # El proveedor falla siempre al nombrar; los temas aún se consolidan.
    temas = LabelClusters(port, FakeProvider(fail_label=True)).execute(55)
    assert port.labeled == []        # ningún nombre persistido
    assert temas == 1                # pero la consolidación de temas continúa


def test_fallo_en_temas_deja_la_corrida_valida():
    port = FakePort(_config(), _clusters())
    assert LabelClusters(port, FakeProvider(fail_themes=True)).execute(55) == 0
    assert port.saved_themes is None


def test_sin_prompt_de_temas_solo_nombra_clusters():
    port = FakePort(_config(prompt_temas=""), _clusters())
    assert LabelClusters(port, FakeProvider()).execute(55) == 0
    assert [cid for cid, _ in port.labeled] == [100, 101]
