"""Invariantes de Regex independientes de HTTP, RE2 y PostgreSQL."""


class InvalidRegex(ValueError):
    pass


def normalize(values: dict[str, object], current: dict[str, object] | None = None) -> dict[str, object]:
    result = dict(values)
    if "nombre" in result:
        name = " ".join(str(result["nombre"]).split())
        if not name:
            raise InvalidRegex("El nombre es obligatorio")
        result["nombre"] = name
    if "condicion" in result and not str(result["condicion"]):
        raise InvalidRegex("La condición es obligatoria")
    if "flags" in result and result["flags"] not in ("", "i"):
        raise InvalidRegex("Solo se admite el indicador i para ignorar mayúsculas")
    if "texto_prueba" in result and not str(result["texto_prueba"]):
        raise InvalidRegex("El texto de prueba es obligatorio")
    if current is None and not all(result.get(field) for field in ("nombre", "condicion", "texto_prueba")):
        raise InvalidRegex("Nombre, condición y texto de prueba son obligatorios")
    return result
