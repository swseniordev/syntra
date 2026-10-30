"""Corrida de clusters de una medición (cola q.analisis).

Lee los embeddings incorporados, los agrupa en k clusters / k_sub subclusters,
versiona una corrida, rotula los clusters y marca cada registro con su cluster.
No conoce PostgreSQL: todo pasa por ``AnalysisPort``. El clustering en sí es puro
(``app.domain.clustering``).
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from app.domain.clustering import hierarchical, summarize_clusters


class AnalysisPort(Protocol):
    def config(self, proceso_id: int) -> dict[str, Any] | None: ...
    def embeddings(self, cuenta_id: int, medicion_id: int, modelo_id: int | None) -> list[dict]: ...
    def create_corrida(self, config: dict, registros: int) -> int: ...
    def save_clusters(self, corrida_id: int, arbol: list[dict]) -> tuple[dict, dict]: ...
    def assign(self, corrida_id: int, cuenta_id: int, medicion_id: int,
               asignaciones: list[tuple]) -> None: ...
    def activate(self, corrida_id: int, medicion_id: int) -> None: ...


class RunAnalysis:
    def __init__(self, persistence: AnalysisPort, seed: int = 0):
        self.persistence = persistence
        self.seed = seed

    def execute(self, proceso_id: int) -> int:
        cfg = self.persistence.config(proceso_id)
        if cfg is None:
            return 0
        filas = self.persistence.embeddings(cfg["cuenta_id"], cfg["medicion_id"],
                                            cfg["modelo_embedding_id"])
        if not filas:
            return 0
        x = np.array([fila["vector"] for fila in filas], dtype=np.float64)
        labels, subs = hierarchical(x, cfg["k"], cfg["k_sub"], self.seed)
        arbol = summarize_clusters(labels, subs)
        corrida_id = self.persistence.create_corrida(cfg, len(filas))
        cluster_map, sub_map = self.persistence.save_clusters(corrida_id, arbol)
        asignaciones = [
            (fila["periodo"], fila["registro_id"], cluster_map[int(labels[i])],
             sub_map[(int(labels[i]), int(subs[i]))])
            for i, fila in enumerate(filas)
        ]
        self.persistence.assign(corrida_id, cfg["cuenta_id"], cfg["medicion_id"], asignaciones)
        self.persistence.activate(corrida_id, cfg["medicion_id"])
        return len(filas)
