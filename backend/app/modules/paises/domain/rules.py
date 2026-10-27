"""Reglas del catálogo de países, independientes de HTTP y PostgreSQL."""

import re


class InvalidCountry(ValueError):
    pass


def normalize(values: dict[str, object]) -> dict[str, object]:
    result = dict(values)
    if "nombre" in result:
        name = " ".join(str(result["nombre"]).split())
        if not name:
            raise InvalidCountry("El nombre es obligatorio")
        result["nombre"] = name
    if "codigo" in result:
        code = str(result["codigo"]).strip()
        if re.fullmatch(r"[A-Z]{2}", code) is None:
            raise InvalidCountry("El código debe contener dos letras mayúsculas")
        result["codigo"] = code
    if "idioma" in result:
        language = str(result["idioma"]).strip()
        if not language:
            raise InvalidCountry("El idioma es obligatorio")
        result["idioma"] = language
    return result
