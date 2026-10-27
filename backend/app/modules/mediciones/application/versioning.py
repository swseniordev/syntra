"""ETag opaco basado en la versión persistida de una medición."""

import hashlib
from typing import Any


def version_tag(measurement: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(measurement["actualizado_en"].isoformat().encode()).hexdigest() + '"'
