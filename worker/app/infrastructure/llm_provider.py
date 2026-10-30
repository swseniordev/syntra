"""Adaptador de proveedor LLM para la cola q.llm.

Por ahora expone un *stub* determinista detrás del puerto ``LLMProvider`` para
poder cablear y probar la cola de punta a punta sin un proveedor real. El
adaptador definitivo (Anthropic u otro modelo de ``cfg.llm_modelo``) se
implementa detrás de esta misma interfaz, sin tocar dominio ni aplicación.
"""

from __future__ import annotations

import hashlib


class StubLLMProvider:
    """Respuestas placeholder y deterministas; NO es un clasificador real.

    Devuelve valores neutros y un vector derivado del hash del texto para que la
    cola funcione en desarrollo. No debe usarse en producción: marca explícita.
    """

    es_placeholder = True

    def __init__(self, dimensiones: int = 256):
        self.dimensiones = dimensiones

    def relevance(self, texto: str, prompt: str, timeout_s: float) -> tuple[int, int | None]:
        # 1 = cumple, por defecto; sin porcentaje porque no hay evaluación real.
        return (1, None)

    def sentiment(self, texto: str, prompt: str, timeout_s: float) -> int:
        return 0  # neutral

    def embedding(self, texto: str, timeout_s: float) -> list[float]:
        semilla = hashlib.sha256((texto or "").encode("utf-8")).digest()
        return [((semilla[i % len(semilla)] / 255.0) * 2.0) - 1.0
                for i in range(self.dimensiones)]


class StubLabelProvider:
    """Etiquetado placeholder y determinista; NO es un clasificador real.

    Nombra cada cluster con las primeras palabras de su muestra y agrupa todos los
    clusters en un único tema. Suficiente para cablear y probar q.analisis en
    desarrollo; el adaptador real (modelo uso='etiquetado') va detrás del mismo puerto.
    """

    es_placeholder = True

    def label_cluster(self, samples: list[str], prompt: str, timeout_s: float) -> tuple[str, str | None]:
        base = next((s for s in samples if s and s.strip()), "")
        nombre = " ".join(base.split()[:5]) or "Sin etiqueta"
        return (nombre, None)

    def summarize_themes(self, clusters: list[dict], prompt: str, timeout_s: float) -> list[dict]:
        if not clusters:
            return []
        return [{"nombre": "General", "resumen": None, "sentimiento": 0, "riesgo": "bajo",
                 "clusters": [c["orden"] for c in clusters]}]
