"""Estado inicial de los registros nuevos según las opciones de la carga."""

from collections.abc import Mapping


def initial_ingest_state(options: Mapping[str, bool]) -> tuple[bool, int]:
    """La incorporación no espera ni depende de la evaluación de relevancia."""
    return bool(options.get("incorporar")), 0 if options.get("relevancia") else 4


def replace_mode(opciones: Mapping[str, object] | None) -> bool:
    """Modo de carga 'reemplazar': lo ausente en la nueva carga se marca eliminado.

    Por defecto la carga es 'upsert' (inserta/actualiza sin borrar). El modo vive
    en ``prc.proceso.opciones.modo`` porque aplica a toda la carga, no al registro.
    """
    return bool(opciones) and opciones.get("modo") == "reemplazar"
