"""Invariantes de Cuentas independientes de FastAPI y PostgreSQL."""

TAXONOMIES = frozenset({"gobierno", "comparativo", "electoral"})


class InvalidAccount(ValueError):
    pass


def normalize(values: dict[str, object], current: dict[str, object] | None = None) -> dict[str, object]:
    result = dict(values)
    if "nombre" in result:
        name = " ".join(str(result["nombre"]).split())
        if not name:
            raise InvalidAccount("El nombre es obligatorio")
        result["nombre"] = name
    for field in ("actor_principal", "entidad"):
        if field in result and result[field] is not None:
            result[field] = " ".join(str(result[field]).split()) or None
    if "taxonomia" in result and result["taxonomia"] is not None:
        if result["taxonomia"] not in TAXONOMIES:
            raise InvalidAccount("Taxonomía no admitida")
    for field in ("prompt_clusters", "prompt_temas"):
        if field in result:
            content = str(result[field])
            if len(content.strip()) < 20:
                raise InvalidAccount(f"{field} debe tener al menos 20 caracteres")
            result[field] = content
    if current is None and not all(result.get(field) for field in ("cliente_id", "nombre", "prompt_clusters", "prompt_temas")):
        raise InvalidAccount("Cliente, nombre y ambos prompts son obligatorios")
    return result
