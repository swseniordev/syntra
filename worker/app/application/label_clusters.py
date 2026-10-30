"""Etiquetado LLM de una corrida: nombra clusters y consolida temas (q.analisis).

Corre después del clustering. Es defensivo: si el proveedor falla al nombrar un
cluster, ese cluster conserva su nombre placeholder y el resto continúa; si falla
la consolidación de temas, la corrida queda igual de válida (solo sin temas). No
conoce PostgreSQL ni el SDK del proveedor: depende de los protocolos de aquí.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.domain.labeling import sanitize_themes

logger = logging.getLogger("syntra.worker.etiquetado")


class LabelProvider(Protocol):
    """Lo mínimo que el etiquetado necesita del proveedor LLM (uso 'etiquetado')."""

    def label_cluster(self, samples: list[str], prompt: str, timeout_s: float) -> tuple[str, str | None]: ...
    def summarize_themes(self, clusters: list[dict], prompt: str, timeout_s: float) -> list[dict]: ...


class LabelPort(Protocol):
    def label_config(self, corrida_id: int) -> dict[str, Any] | None: ...
    def cluster_samples(self, corrida_id: int, max_per_cluster: int) -> list[dict]: ...
    def save_cluster_label(self, cluster_id: int, nombre: str, descripcion: str | None) -> None: ...
    def save_themes(self, corrida_id: int, cuenta_id: int, medicion_id: int,
                    themes: list[dict], orden_to_cluster: dict[int, int]) -> int: ...


SAMPLES_PER_CLUSTER = 8


class LabelClusters:
    def __init__(self, persistence: LabelPort, provider: LabelProvider):
        self.persistence = persistence
        self.provider = provider

    def execute(self, corrida_id: int) -> int:
        cfg = self.persistence.label_config(corrida_id)
        if cfg is None:
            return 0
        clusters = self.persistence.cluster_samples(corrida_id, SAMPLES_PER_CLUSTER)
        if not clusters:
            return 0
        budget = cfg["timeout_paso_s"]
        for cluster in clusters:
            if not cfg["prompt_cluster"]:
                break
            try:
                nombre, descripcion = self.provider.label_cluster(
                    cluster["samples"], cfg["prompt_cluster"], budget)
                self.persistence.save_cluster_label(cluster["cluster_id"], nombre, descripcion)
            except Exception:  # noqa: BLE001 — un cluster sin etiquetar no tumba la corrida
                logger.warning("No se etiquetó el cluster %s de la corrida %s",
                               cluster["cluster_id"], corrida_id)
        if not cfg["prompt_temas"]:
            return 0
        resumen = [{"orden": c["orden"], "nombre": c["nombre"], "registros": c["registros"]}
                   for c in clusters]
        try:
            propuestos = self.provider.summarize_themes(resumen, cfg["prompt_temas"], budget)
        except Exception:  # noqa: BLE001 — sin temas la corrida sigue siendo válida
            logger.warning("No se consolidaron los temas de la corrida %s", corrida_id)
            return 0
        themes = sanitize_themes(propuestos, [c["orden"] for c in clusters])
        if not themes:
            return 0
        orden_to_cluster = {c["orden"]: c["cluster_id"] for c in clusters}
        return self.persistence.save_themes(corrida_id, cfg["cuenta_id"],
                                            cfg["medicion_id"], themes, orden_to_cluster)
