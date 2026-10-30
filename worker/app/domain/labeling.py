"""Normalización pura del etiquetado de clusters y temas (sin I/O ni proveedor).

Tras el clustering, un paso LLM nombra cada cluster y consolida los clusters en
temas ejecutivos. Aquí viven solo las reglas de validación y saneo de esa salida;
el dominio de sentimiento/riesgo sigue el esquema (`ana.tema`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

SENTIMIENTOS = (-1, 0, 1)        # negativo · neutral · positivo
RIESGOS = ("bajo", "medio", "alto")
MAX_TEMAS = 6                    # el prompt de temas pide máximo 6


def clean_label(value: object, max_len: int = 120) -> str:
    """Colapsa espacios y recorta; un nombre de cluster/tema nunca es vacío."""
    texto = " ".join(str(value or "").split()).strip()
    if not texto:
        return "Sin etiqueta"
    return texto[:max_len].rstrip()


def clean_text(value: object, max_len: int = 500) -> str | None:
    texto = " ".join(str(value or "").split()).strip()
    return texto[:max_len].rstrip() or None


def valid_sentiment(value: object) -> bool:
    return value in SENTIMIENTOS


def valid_risk(value: object) -> bool:
    return value in RIESGOS


def sanitize_theme(raw: Mapping[str, object], valid_ordenes: Sequence[int]) -> dict:
    """Valida un tema propuesto y lo liga solo a clusters existentes de la corrida.

    Lanza ``ValueError`` si no referencia ningún cluster válido: un tema huérfano
    no aporta y ensuciaría ``ana.cluster_tema``.
    """
    allowed = set(valid_ordenes)
    ordenes = [int(o) for o in (raw.get("clusters") or []) if isinstance(o, int) and o in allowed]
    if not ordenes:
        raise ValueError("Tema sin clusters válidos")
    sentimiento = raw.get("sentimiento")
    riesgo = raw.get("riesgo")
    return {"nombre": clean_label(raw.get("nombre")),
            "resumen": clean_text(raw.get("resumen")),
            "sentimiento": sentimiento if valid_sentiment(sentimiento) else None,
            "riesgo": riesgo if valid_risk(riesgo) else None,
            "clusters": sorted(set(ordenes))}


def sanitize_themes(raws: Sequence[Mapping[str, object]], valid_ordenes: Sequence[int]) -> list[dict]:
    """Saneo del lote de temas: descarta los inválidos y recorta a MAX_TEMAS."""
    temas: list[dict] = []
    for raw in raws:
        try:
            temas.append(sanitize_theme(raw, valid_ordenes))
        except (ValueError, TypeError, AttributeError):
            continue
        if len(temas) >= MAX_TEMAS:
            break
    return temas
