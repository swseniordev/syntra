"""Valida el documento OpenAPI completo sin resolver ni ejecutar endpoints."""

from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml


class UniqueLoader(yaml.SafeLoader):
    """La carga YAML normal aceptaría silenciosamente claves duplicadas."""


def _mapping(loader: UniqueLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Clave YAML duplicada en línea {key_node.start_mark.line + 1}: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def validate(path: Path) -> tuple[int, int]:
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
    if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith("3.1."):
        raise ValueError("La versión OpenAPI debe ser 3.1")
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("Faltan paths")
    operations = {}
    references = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                references.add(reference)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    for reference in references:
        if not reference.startswith("#/"):
            raise ValueError(f"Referencia externa no admitida: {reference}")
        node: object = document
        for part in reference[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                raise ValueError(f"Referencia sin destino: {reference}")
            node = node[part]

    verbs = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    for route, item in paths.items():
        if not isinstance(item, dict) or not route.startswith("/"):
            raise ValueError(f"Ruta inválida: {route}")
        placeholders = set(re.findall(r"\{([^{}]+)\}", route))
        for verb, operation in item.items():
            if verb not in verbs:
                continue
            if not isinstance(operation, dict):
                raise ValueError(f"Operación inválida: {verb} {route}")
            identifier = operation.get("operationId")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError(f"Falta operationId en {verb} {route}")
            if identifier in operations:
                raise ValueError(f"operationId duplicado: {identifier}")
            operations[identifier] = (verb, route)
            if not isinstance(operation.get("responses"), dict) or not operation["responses"]:
                raise ValueError(f"Faltan respuestas en {verb} {route}")
            params = item.get("parameters", []) + operation.get("parameters", [])
            declared = {param.get("name") for param in params if isinstance(param, dict)
                        and param.get("in") == "path" and param.get("required") is True}
            if placeholders != declared:
                raise ValueError(f"Parámetros de ruta incongruentes en {verb} {route}")
    return len(paths), len(operations)


if __name__ == "__main__":
    source = Path(__file__).resolve().parents[2] / "docs" / "especificaciones" / "Syntra_openapi.yaml"
    try:
        routes, operations = validate(source)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"OpenAPI inválido: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"OpenAPI completo válido en sintaxis, referencias e IDs: {routes} paths, {operations} operaciones")
