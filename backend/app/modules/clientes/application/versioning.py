"""Versión opaca para concurrencia optimista de Clientes."""

import hashlib
from typing import Any


def version_tag(client: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(client["actualizado_en"].isoformat().encode()).hexdigest() + '"'
