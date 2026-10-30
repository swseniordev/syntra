"""Reparto puro: de un volumen de registros a los chunks de tareas q.llm.

El proceso de ingesta, al completarse, reparte los registros recién incorporados
en N tareas de cómputo paralelas. Aquí viven solo las decisiones (sin I/O):
cuándo hace falta repartir, bajo qué tipo de proceso, y cómo trocear el rango de
``registro_id`` por período en ventanas keyset. Cada ventana es una tarea q.llm.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

# Computaciones que disparan el reparto a q.llm (claves de opciones al incorporar).
COMPUTOS = ("relevancia", "sentimiento", "clusters")


def fanout_needed(options: Mapping[str, object]) -> bool:
    """Solo se reparte si el usuario pidió calcular algo sobre los registros."""
    return any(bool(options.get(clave)) for clave in COMPUTOS)


def compute_proceso_tipo(options: Mapping[str, object]) -> str:
    """Código de cat.tipo_proceso que rotula el proceso de cómputo.

    Debe ser SIEMPRE un tipo enrutado a q.llm, porque el reparto encola tareas
    q.llm (incluido el embedding, prerrequisito del clustering). El catálogo no
    tiene un tipo 'embedding', así que clusters-solo reutiliza el rótulo q.llm
    'relevancia'. Nunca 'analisis': ese tipo enruta a q.analisis y lo crea el
    encadenado posterior, no el reparto.
    """
    if options.get("sentimiento"):
        return "sentimiento"
    return "relevancia"


def plan_chunks(periodo: int, min_id: int, max_id: int, count: int,
                chunk_size: int) -> list[dict]:
    """Trocea [min_id, max_id] de un período en ventanas keyset de ~chunk_size.

    Usa ventanas contiguas de ancho uniforme: con ``registro_id`` de una secuencia
    quedan parejas en la práctica, y el worker filtra por estado dentro de cada
    ventana, de modo que una ventana vacía o algo cargada no rompe nada.
    """
    if count <= 0 or max_id < min_id or chunk_size < 1:
        return []
    ventanas = max(1, math.ceil(count / chunk_size))
    span = max_id - min_id + 1
    ancho = max(1, math.ceil(span / ventanas))
    chunks: list[dict] = []
    desde = min_id
    indice = 0
    while desde <= max_id:
        hasta = min(max_id, desde + ancho - 1)
        chunks.append({"clave": f"chunk:{periodo}:{indice:06d}", "periodo": periodo,
                       "desde": desde, "hasta": hasta})
        desde = hasta + 1
        indice += 1
    return chunks
