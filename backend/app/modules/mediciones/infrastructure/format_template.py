"""Construcción de planillas vacías a partir de encabezados configurados."""

from __future__ import annotations

from io import BytesIO
from typing import Iterable

from openpyxl import Workbook


def source_columns(mapping: Iterable[dict]) -> list[str]:
    """Aplana las columnas origen del mapeo conservando su orden y sin duplicados."""
    result: list[str] = []
    seen: set[str] = set()
    for item in mapping:
        for raw in item.get("columnas_origen") or []:
            column = str(raw).strip()
            if column and column not in seen:
                seen.add(column)
                result.append(column)
    return result


def build_xlsx_template(columns: list[str]) -> bytes:
    if not columns:
        raise ValueError("El formato no tiene columnas de origen configuradas")
    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet("Plantilla")
    worksheet.append(columns)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
