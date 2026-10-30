"""Clustering jerárquico puro sobre embeddings (solo numpy, sin I/O).

Agrupa los vectores de una medición en ``k`` clusters y, dentro de cada uno, en
``k_sub`` subclusters (algoritmo ``kmeans_jerarquico`` del esquema). Determinista
por semilla para que una corrida sea reproducible y auditable.
"""

from __future__ import annotations

import numpy as np


def parse_vector(texto: str) -> list[float]:
    """Convierte el literal halfvec '[a,b,...]' de pgvector en floats."""
    cuerpo = (texto or "").strip().lstrip("[").rstrip("]").strip()
    if not cuerpo:
        return []
    return [float(parte) for parte in cuerpo.split(",")]


def _assign(x: np.ndarray, centros: np.ndarray) -> np.ndarray:
    # ||x-c||² = ||x||² - 2·x·c + ||c||²  (sin materializar el tensor n×k×d)
    distancia = (x * x).sum(1)[:, None] - 2 * x @ centros.T + (centros * centros).sum(1)[None, :]
    return distancia.argmin(1)


def kmeans(x: np.ndarray, k: int, seed: int = 0, iters: int = 50) -> np.ndarray:
    """Etiquetas 0..k-1 por fila. ``k`` se recorta al nº de muestras."""
    n = x.shape[0]
    if n == 0:
        return np.empty(0, dtype=int)
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    centros = x[rng.choice(n, size=k, replace=False)].astype(np.float64)
    labels = np.zeros(n, dtype=int)
    for paso in range(iters):
        nuevo = _assign(x, centros)
        if paso and np.array_equal(nuevo, labels):
            return labels
        labels = nuevo
        for c in range(k):
            miembros = x[labels == c]
            centros[c] = miembros.mean(axis=0) if len(miembros) else x[rng.integers(n)]
    return labels


def hierarchical(x: np.ndarray, k: int, k_sub: int, seed: int = 0
                 ) -> tuple[np.ndarray, np.ndarray]:
    """(cluster, subcluster) por fila: KMeans de ``k`` y luego ``k_sub`` dentro."""
    labels = kmeans(x, k, seed)
    subs = np.zeros(x.shape[0], dtype=int)
    for c in np.unique(labels):
        idx = np.where(labels == c)[0]
        subs[idx] = kmeans(x[idx], k_sub, seed + 1 + int(c))
    return labels, subs


def summarize_clusters(labels: np.ndarray, subs: np.ndarray) -> list[dict]:
    """Árbol de clusters con conteos y orden estable, listo para persistir.

    Cada cluster: ``{"idx", "orden", "registros", "subs": [{"idx","orden","registros"}]}``.
    El orden sigue el índice de cluster/subcluster (determinista).
    """
    arbol: list[dict] = []
    for orden, c in enumerate(sorted({int(v) for v in labels})):
        en_cluster = labels == c
        hijos = []
        for sub_orden, s in enumerate(sorted({int(v) for v in subs[en_cluster]})):
            hijos.append({"idx": s, "orden": sub_orden,
                          "registros": int((en_cluster & (subs == s)).sum())})
        arbol.append({"idx": c, "orden": orden, "registros": int(en_cluster.sum()),
                      "subs": hijos})
    return arbol
