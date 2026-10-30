"""Normalización pura de resultados Apify a filas de dat.registro.

Apify entrega un *dataset* de objetos JSON cuya forma depende del actor. Este
módulo traduce cada item a la misma fila que produce la ingesta de archivos
(:mod:`app.domain.talkwalker`), reutilizando su identidad de URL para que la
deduplicación por huella sea idéntica a la de los archivos.

Los nombres de campo por actor son el punto a confirmar contra el *input/output
schema* real de cada actor de Apify (p. ej. ``apidojo/tweet-scraper``). Se
resuelven con listas de candidatos y se ajustan aquí, sin tocar el consumidor.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.domain.talkwalker import RejectedRow, _number, url_identity

# Redes soportadas y su alias de catálogo cat.red.codigo.
RED_CODES = {"x", "tiktok", "youtube", "facebook", "instagram"}

# Estados terminales de una corrida de Apify (run.status).
_TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT", "TIMING-OUT"}


def is_terminal(status: str | None) -> bool:
    return str(status or "").upper() in _TERMINAL


def succeeded(status: str | None) -> bool:
    return str(status or "").upper() == "SUCCEEDED"


# Tope defensivo de registros por corrida (cuota): un max_registros mal configurado
# en el catálogo no debe disparar una corrida costosa.
MAX_ITEMS_CEILING = 10_000

# Actores que NO admiten búsqueda por palabras (necesitan URLs/handles de origen).
# Se rechazan ANTES de llamar a Apify para no gastar cuota en un 400 seguro.
_SIN_BUSQUEDA = {"apify/facebook-posts-scraper"}


def build_run_input(actor: str, keywords: list[str], max_records: int,
                    transcribe: bool = False, countries: list[str] | None = None) -> dict[str, Any]:
    """Arma el ``run_input`` del actor a partir de la configuración del scraper.

    El límite se acota a ``max_records`` (ya validado contra
    ``cfg.actor_scraping.max_registros`` por quien encola) y a un tope de cuota.
    Los nombres de clave siguen los *input schema* publicados de cada actor;
    actores no reconocidos usan un esquema genérico de búsqueda.
    """
    if max_records < 1:
        raise ValueError("El máximo de registros debe ser positivo")
    max_records = min(max_records, MAX_ITEMS_CEILING)
    terms = [term for term in (keyword.strip() for keyword in keywords) if term]
    if not terms:
        raise ValueError("El scraper no tiene palabras de búsqueda para esta red")
    name = actor.lower()
    if name in _SIN_BUSQUEDA:
        raise ValueError(f"El actor {actor} no admite búsqueda por palabras; "
                         "usa un actor de búsqueda o configura URLs de origen")
    if name == "apidojo/tweet-scraper":
        return {"searchTerms": terms, "maxItems": max_records, "sort": "Latest"}
    if name == "clockworks/tiktok-scraper":
        return {"searchQueries": terms, "resultsPerPage": max_records}
    if name == "streamers/youtube-scraper":
        return {"searchKeywords": " ".join(terms), "maxResults": max_records,
                "subtitles": bool(transcribe)}
    if name == "apify/instagram-scraper":
        return {"search": terms[0], "searchType": "hashtag", "resultsLimit": max_records}
    # Esquema genérico: la mayoría de actores acepta una lista de términos y un tope.
    return {"searchStringsArray": terms, "maxItems": max_records}


# Candidatos de campo por destino, probados en orden hasta hallar uno presente.
_CANDIDATES: dict[str, tuple[str, ...]] = {
    "url": ("url", "postUrl", "webVideoUrl", "link", "tweetUrl"),
    "titulo": ("title", "name"),
    "texto": ("text", "fullText", "caption", "content", "description", "title"),
    "fecha_publicacion": ("createdAt", "publishedAt", "timestamp", "date", "created_at", "uploadDate"),
    "fecha_indexado": ("scrapedAt", "indexedAt"),
    "idioma": ("lang", "language"),
    "url_padre": ("inReplyToUrl", "parentUrl", "replyToUrl"),
    "autor_id_ext": ("authorId", "ownerId", "userId", "channelId"),
    "autor_usuario": ("username", "authorUsername", "ownerUsername", "handle", "screenName"),
    "autor_nombre": ("authorName", "ownerFullName", "fullName", "name", "channelName"),
    "autor_seguidores": ("followers", "authorFollowers", "followersCount"),
    "pais": ("country", "countryCode"),
    "region": ("region", "state"),
    "ciudad": ("city",),
    "likes": ("likes", "likesCount", "diggCount", "favoriteCount"),
    "comentarios": ("comments", "commentsCount", "replyCount", "commentCount"),
    "compartidos": ("shares", "sharesCount", "retweetCount", "shareCount"),
    "reproducciones": ("views", "viewsCount", "playCount", "videoViewCount"),
}

_TIPO_POR_RED = {"x": "texto", "tiktok": "video", "youtube": "video",
                 "facebook": "texto", "instagram": "imagen"}


def _first(item: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = item.get(name)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _parse_date(value: Any, minimum: date | None) -> datetime:
    """Acepta ISO 8601 (lo habitual en Apify) o epoch en segundos/milisegundos."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
    else:
        raw = str(value or "").strip()
        if not raw:
            raise RejectedRow("Falta la fecha de publicación")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RejectedRow("Fecha Apify no es ISO 8601 ni epoch") from exc
    parsed = parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if minimum is not None and parsed.date() < minimum:
        raise RejectedRow("Fecha anterior al mínimo del formato; requiere revisión")
    return parsed


def map_item(red_code: str, red_id: int, item: dict[str, Any],
             minimum: date | None = None) -> dict[str, Any]:
    """Traduce un item del dataset de Apify a una fila de dat.registro.

    Lanza :class:`RejectedRow` si el item no tiene URL ni fecha utilizables, de
    modo que el consumidor lo cuente como rechazado sin abortar la corrida.
    """
    url = str(_first(item, _CANDIDATES["url"]) or "").strip()
    if not url:
        raise RejectedRow("El item de Apify no trae URL")
    published = _parse_date(_first(item, _CANDIDATES["fecha_publicacion"]), minimum)
    indexed_raw = _first(item, _CANDIDATES["fecha_indexado"])
    canonical, fingerprint, legacy = url_identity(url)
    row: dict[str, Any] = {
        "red_id": red_id, "url": url, "url_canonica": canonical,
        "url_hash": fingerprint, "huellas_heredadas": legacy,
        "fecha_publicacion": published,
        "fecha_indexado": _parse_date(indexed_raw, None) if indexed_raw is not None else None,
        "titulo": _first(item, _CANDIDATES["titulo"]),
        "texto": _first(item, _CANDIDATES["texto"]),
        "idioma": _first(item, _CANDIDATES["idioma"]),
        "tipo_contenido": _TIPO_POR_RED.get(red_code, "texto"),
        "url_padre": _first(item, _CANDIDATES["url_padre"]),
        "autor_id_ext": _first(item, _CANDIDATES["autor_id_ext"]),
        "autor_usuario": _first(item, _CANDIDATES["autor_usuario"]),
        "autor_nombre": _first(item, _CANDIDATES["autor_nombre"]),
        "autor_seguidores": _number(_first(item, _CANDIDATES["autor_seguidores"])),
        "pais": _first(item, _CANDIDATES["pais"]),
        "region": _first(item, _CANDIDATES["region"]),
        "ciudad": _first(item, _CANDIDATES["ciudad"]),
        "es_rt": bool(item.get("isRetweet") or item.get("isRepost") or False),
        "es_comentario": _first(item, _CANDIDATES["url_padre"]) is not None,
        "media_urls": None,
        "extra": {"actor_item": True},
        "sentimiento_fuente": None,
        "likes": _number(_first(item, _CANDIDATES["likes"])),
        "comentarios": _number(_first(item, _CANDIDATES["comentarios"])),
        "compartidos": _number(_first(item, _CANDIDATES["compartidos"])),
        "reproducciones": _number(_first(item, _CANDIDATES["reproducciones"])),
        "alcance": None,
    }
    return row
