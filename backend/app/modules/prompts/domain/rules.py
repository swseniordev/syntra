"""Invariantes de plantillas de prompts independientes de transporte y almacenamiento."""

PROMPT_TYPES = frozenset({"cluster", "temas", "relevancia", "sentimiento", "etiqueta_cluster"})
NETWORKS = frozenset({"x", "tiktok", "youtube", "facebook", "instagram", "medios"})
PER_NETWORK_TYPES = frozenset({"relevancia", "sentimiento"})


class InvalidPrompt(ValueError):
    pass


def normalize(values: dict[str, object], current: dict[str, object] | None = None) -> dict[str, object]:
    result = dict(values)
    kind = result.get("tipo", current["tipo"] if current else None)
    network = result.get("red", current["red"] if current else None)
    state = result.get("estado_id", current["estado_id"] if current else 1)
    default = result.get("por_defecto", current["por_defecto"] if current else False)
    if kind not in PROMPT_TYPES:
        raise InvalidPrompt("Tipo de prompt inválido")
    if network is not None and network not in NETWORKS:
        raise InvalidPrompt("Red no admitida")
    if network is not None and kind not in PER_NETWORK_TYPES:
        raise InvalidPrompt("Solo relevancia y sentimiento admiten ajuste por red")
    if default and state != 1:
        raise InvalidPrompt("Un prompt por defecto debe estar activo")
    if "nombre" in result:
        name = " ".join(str(result["nombre"]).split())
        if not name:
            raise InvalidPrompt("El nombre es obligatorio")
        result["nombre"] = name
    if "contenido" in result:
        content = str(result["contenido"])
        if len(content.strip()) < 20:
            raise InvalidPrompt("El prompt debe tener al menos 20 caracteres")
        result["contenido"] = content
    return result
