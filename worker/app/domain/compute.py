"""Decisiones puras del cómputo por registro (relevancia · sentimiento · embedding).

No conoce PostgreSQL ni el proveedor LLM. Los estados de paso siguen la
convención del esquema (cat.estado_paso):
    0 pendiente · 1 en curso · 2 ok · 3 error · 4 no aplica
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib

PENDIENTE = 0
EN_CURSO = 1
OK = 2
ERROR = 3
NO_APLICA = 4

# Pasos que la cola q.llm sabe calcular, en orden estable y determinista.
RELEVANCIA = "relevancia"
SENTIMIENTO = "sentimiento"
EMBEDDING = "embedding"
PASOS = (RELEVANCIA, SENTIMIENTO, EMBEDDING)

# dat.registro_estado expone un st_<paso> por cada cómputo.
COLUMNA_ESTADO = {
    RELEVANCIA: "st_relevancia",
    SENTIMIENTO: "st_sentimiento",
    EMBEDDING: "st_embedding",
}


def texto_fingerprint(texto: str | None) -> bytes:
    """Huella del texto que decide si el embedding debe recalcularse."""
    return hashlib.sha256(("txt:" + (texto or "").strip()).encode("utf-8")).digest()


def embedding_vigente(actual: bytes | None, nuevo: bytes) -> bool:
    """El embedding solo se recalcula cuando cambió el texto del registro."""
    return actual is not None and actual == nuevo


def pasos_pendientes(estados: Mapping[str, int]) -> tuple[str, ...]:
    """Pasos todavía en 0 (pendiente); el cómputo es idempotente por registro."""
    return tuple(paso for paso in PASOS if estados.get(COLUMNA_ESTADO[paso]) == PENDIENTE)


def relevancia_valida(codigo: int) -> bool:
    """dat.registro_estado.relevancia: 1 cumple · 2 no cumple (0 queda pendiente)."""
    return codigo in (1, 2)


def sentimiento_valido(valor: int) -> bool:
    """dat.registro_estado.sentimiento: -1 negativo · 0 neutral · 1 positivo."""
    return valor in (-1, 0, 1)
