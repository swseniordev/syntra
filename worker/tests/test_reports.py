"""Protección del artefacto XLSX sin conexión de red."""

from pathlib import Path
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

from openpyxl import Workbook, load_workbook

import pytest

from app.reports import ReportQueue, _private_root, _safe_cell


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1:A2)", "-3+4", "@SUM(1)", "  =HYPERLINK(\"x\")"])
def test_excel_formula_is_escaped(value):
    assert _safe_cell(value) == "'" + value


def test_private_root_rejects_relative_and_repository_paths():
    with pytest.raises(ValueError):
        _private_root(Path("reports"))
    repo = Path(__file__).resolve().parents[2]
    with pytest.raises(ValueError):
        _private_root(repo / "frontend" / "public" / "reports")


def test_xlsx_is_published_only_after_complete_write_and_retry(tmp_path, monkeypatch):
    # La validación de raíz privada se prueba aparte; aquí se aíslan los archivos bajo pytest.
    monkeypatch.setattr("app.reports._private_root", lambda root: root)
    queue = ReportQueue(SimpleNamespace(report_root=tmp_path), connect=lambda: nullcontext(object()))
    date = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    row = {"fecha": date, "id": 7, "usuario_id": 1, "modulo": "clientes", "accion": "crear",
           "entidad_tipo": "Cliente", "entidad_id": "3", "entidad_nombre": "Cliente de ensayo",
           "antes": None, "despues": {"nombre": "Cliente de ensayo"}, "detalle": None,
           "ip": None, "request_id": None}
    monkeypatch.setattr(queue, "_rows", lambda _conn, _filters, _cutoff: iter([row]))
    original_save = Workbook.save

    def interrupted_save(self, filename):
        original_save(self, filename)
        Path(filename).write_bytes(b"archivo incompleto")
        raise OSError("fallo controlado durante la escritura")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(Workbook, "save", interrupted_save)
        with pytest.raises(OSError):
            queue._write(19, {"modulo": "clientes"}, date)
    assert not (tmp_path / "auditoria-19.xlsx").exists()
    assert (tmp_path / "auditoria-19.tmp").exists()
    assert Workbook.save is original_save
    assert queue._write(19, {"modulo": "clientes"}, date) == 1
    assert not (tmp_path / "auditoria-19.tmp").exists()
    final = tmp_path / "auditoria-19.xlsx"
    assert final.exists()
    workbook = load_workbook(final, read_only=True)
    try:
        assert list(workbook.worksheets[0].values)[1][7] == "Cliente de ensayo"
    finally:
        workbook.close()
