"""Estado inicial de los registros nuevos según las opciones de la carga."""

from collections.abc import Mapping


def initial_ingest_state(options: Mapping[str, bool]) -> tuple[bool, int]:
    """La incorporación no espera ni depende de la evaluación de relevancia."""
    return bool(options.get("incorporar")), 0 if options.get("relevancia") else 4
