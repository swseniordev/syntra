"""Lectura y normalización pura de filas según cfg.formato_columna."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo


class RejectedRow(ValueError):
    """Fila que no satisface el mapeo técnico aprobado."""


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _number(value: Any) -> int | None:
    if not _present(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        parsed = int(str(value).replace(",", "").strip())
    except ValueError as exc:
        raise RejectedRow("Número inválido") from exc
    return parsed


def _date(value: Any, zone: ZoneInfo, minimum: date | None) -> datetime | None:
    if not _present(value):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.strptime(str(value).strip(), "%d/%m/%y %H:%M:%S")
        except ValueError as exc:
            raise RejectedRow("Fecha incompatible con dd/MM/yy HH:MM:ss") from exc
    if parsed.tzinfo is None:
        candidates = []
        for fold in (0, 1):
            local = parsed.replace(tzinfo=zone, fold=fold)
            instant = local.astimezone(timezone.utc)
            if instant.astimezone(zone).replace(tzinfo=None) == parsed:
                candidates.append(instant)
        if not candidates or len(set(candidates)) != 1:
            raise RejectedRow("Fecha local inexistente o ambigua en la zona del formato")
        parsed = candidates[0]
    else:
        parsed = parsed.astimezone(timezone.utc)
    if minimum is not None and parsed.astimezone(zone).date() < minimum:
        raise RejectedRow("Fecha anterior al mínimo del formato; requiere revisión")
    return parsed


def _red(value: Any, networks: dict[str, int]) -> int:
    parts = [part.strip().upper() for part in str(value or "").split(",")]
    final = parts[-1].removeprefix("SOCIALMEDIA_")
    aliases = {"TWITTER": "x", "X": "x", "TIKTOK": "tiktok", "YOUTUBE": "youtube",
               "FACEBOOK": "facebook", "INSTAGRAM": "instagram"}
    if len(parts) == 2 and parts[0] == "SOCIALMEDIA" and final in aliases:
        code = aliases[final]
    elif len(parts) == 2 and (parts[0], final) in {
        ("ONLINENEWS", "ONLINENEWS_OTHER"),
        ("ONLINENEWS", "ONLINENEWS_PRESSRELEASES"),
        ("ONLINENEWS", "ONLINENEWS_NEWSPAPER"),
        ("BLOG", "BLOG_OTHER"),
        ("MESSAGEBOARD", "MESSAGEBOARD_OTHER"),
    }:
        code = "medios"
    else:
        raise RejectedRow("Red social desconocida")
    if code not in networks:
        raise RejectedRow("La red no existe en el catálogo")
    return networks[code]


def url_identity(value: Any) -> tuple[str, bytes, tuple[bytes, ...]]:
    """URL canónica para nuevas huellas y variantes de lectura MD5 heredadas.

    Conserva ruta, mayúsculas, consulta y fragmento. Solo equipara el esquema
    HTTP/HTTPS y una barra final de la ruta. La función SQL oficial elimina
    el fragmento al producir la huella SHA-256.
    """
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in {"http", "https"} or not parts.netloc or parts.hostname is None:
            raise ValueError
        if any(char.isspace() for char in raw):
            raise ValueError
        # urlsplit acepta puertos inválidos; exigir validación antes de insertar.
        _ = parts.port
    except ValueError as exc:
        raise RejectedRow("URL inválida: se requiere http:// o https:// y un host válido") from exc
    canonical_path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    canonical = urlunsplit(("https", parts.netloc, canonical_path, parts.query, parts.fragment))
    new_hash = hashlib.sha256(("url:" + canonical.split("#", 1)[0]).encode("utf-8")).digest()
    variants = {raw}
    for scheme in ("http", "https"):
        for path in {canonical_path, canonical_path + "/"}:
            variants.add(urlunsplit((scheme, parts.netloc, path, parts.query, parts.fragment)))
    # No reescribe huellas históricas. La consulta puede encontrar el MD5
    # anterior de cualquiera de las variantes aprobadas de la misma URL.
    legacy = tuple(sorted({hashlib.md5(url.encode("utf-8")).digest() for url in variants}))
    return canonical, new_hash, legacy


def map_row(raw: dict[str, Any], mapping: list[dict], networks: dict[str, int],
            zone_name: str, minimum: date | None) -> dict[str, Any]:
    """Interpreta únicamente transformaciones presentes en el catálogo técnico."""
    zone = ZoneInfo(zone_name)
    result: dict[str, Any] = {}
    for rule in mapping:
        inputs = [raw.get(name) for name in rule["columnas_origen"]]
        present = [value for value in inputs if _present(value)]
        if rule["requerido"] and not present:
            raise RejectedRow(f"Falta el campo requerido {rule['campo_destino']}")
        operation = rule["transformacion"]
        value: Any = None
        if operation in ("directo", "coalesce"):
            value = present[0] if present else None
        elif operation == "fecha":
            value = _date(present[0] if present else None, zone, minimum)
        elif operation == "red_desde_source_type":
            value = _red(present[0] if present else None, networks)
        elif operation == "mayusculas":
            value = str(present[0]).strip().upper() if present else None
        elif operation == "entero":
            value = _number(present[0]) if present else None
        elif operation == "suma":
            value = sum(_number(item) or 0 for item in present) if present else None
        elif operation == "lista":
            value = [str(item).strip() for item in present]
        elif operation.startswith("contiene:"):
            value = any(operation.removeprefix("contiene:") in str(item).split(",") for item in present)
        elif operation == "json":
            value = {name: (raw[name].isoformat() if isinstance(raw[name], (date, datetime)) else raw[name])
                     for name in rule["columnas_origen"] if _present(raw.get(name))}
        else:
            raise RejectedRow("Transformación de formato no admitida")
        if rule["campo_destino"] in {"autor_seguidores", "likes", "comentarios", "compartidos",
                                     "reproducciones", "alcance", "sentimiento_fuente"}:
            value = _number(value)
        result[rule["campo_destino"]] = value
    published = result.get("fecha_publicacion")
    if not isinstance(published, datetime):
        raise RejectedRow("Falta la fecha de publicación")
    url = str(result.get("url") or "").strip()
    if not url:
        raise RejectedRow("Falta la URL")
    result["url"] = url
    canonical, fingerprint, legacy = url_identity(url)
    result["url_canonica"] = canonical
    result["url_hash"] = fingerprint
    result["huellas_heredadas"] = legacy
    return result
