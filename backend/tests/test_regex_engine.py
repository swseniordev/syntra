"""RE2 real; ninguna prueba de JavaScript o del motor backtracking de Python."""

from app.modules.regex.domain.rules import InvalidRegex, normalize
from app.modules.regex.infrastructure.re2_engine import RE2Evaluator
import pytest


def test_re2_coincidencias_y_posiciones():
    result = RE2Evaluator().test("agua", "i", "Agua y agua")
    assert result == {"valida": True, "cumple": True, "coincidencias": [
        {"inicio": 0, "fin": 4, "texto": "Agua"},
        {"inicio": 7, "fin": 11, "texto": "agua"},
    ], "error": None}


@pytest.mark.parametrize("condition", ["(", "(?=agua)agua", r"(a)\1"])
def test_re2_rechaza_patrones_no_compatibles(condition):
    result = RE2Evaluator().test(condition, "i", "agua aa")
    assert result["valida"] is False
    assert result["coincidencias"] == []


def test_reglas_de_dominio_y_flags():
    assert normalize({"nombre": "  Crisis   del\tagua ", "condicion": "agua", "texto_prueba": "agua"})["nombre"] == "Crisis del agua"
    with pytest.raises(InvalidRegex):
        normalize({"nombre": "X", "condicion": "agua", "texto_prueba": "agua", "flags": "g"})
