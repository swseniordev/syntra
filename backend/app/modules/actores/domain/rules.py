"""Reglas del catálogo de actores de Apify, independientes de HTTP y PostgreSQL."""

import re

REDES = {"x", "tiktok", "youtube", "facebook", "instagram"}
USOS = {"busqueda", "metricas", "perfil"}
_ACTOR = re.compile(r"^[\w.-]+/[\w.-]+$")
_ENTEROS = ("max_registros", "max_urls_por_corrida", "memoria_mb")


class InvalidActor(ValueError):
    pass


def normalize(values: dict[str, object]) -> dict[str, object]:
    result = dict(values)
    if "nombre" in result:
        name = " ".join(str(result["nombre"]).split())
        if not name:
            raise InvalidActor("El nombre es obligatorio")
        result["nombre"] = name
    if "actor" in result:
        actor = str(result["actor"]).strip()
        if _ACTOR.fullmatch(actor) is None:
            raise InvalidActor("El actor debe tener la forma usuario/actor")
        result["actor"] = actor
    if "red" in result:
        red = str(result["red"]).strip().lower()
        if red not in REDES:
            raise InvalidActor("Red no soportada")
        result["red"] = red
    if "uso" in result:
        uso = str(result["uso"]).strip().lower()
        if uso not in USOS:
            raise InvalidActor("Uso no válido")
        result["uso"] = uso
    for field in _ENTEROS:
        if field in result and result[field] is not None:
            try:
                value = int(result[field])
            except (TypeError, ValueError) as exc:
                raise InvalidActor(f"{field} debe ser un entero") from exc
            if value < 1:
                raise InvalidActor(f"{field} debe ser positivo")
            result[field] = value
    if "nota" in result and result["nota"] is not None:
        result["nota"] = str(result["nota"]).strip() or None
    return result
