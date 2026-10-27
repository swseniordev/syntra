"""Adaptador del motor RE2 usado al probar y guardar expresiones."""

import re2


class RE2Evaluator:
    def test(self, condition: str, flags: str, text: str) -> dict:
        options = re2.Options()
        options.case_sensitive = "i" not in flags
        options.log_errors = False
        try:
            expression = re2.compile(condition, options=options)
        except re2.error:
            return {"valida": False, "cumple": False, "coincidencias": [],
                    "error": "La condición no es válida en RE2"}
        matches = [{"inicio": match.start(), "fin": match.end(), "texto": match.group(0)}
                   for match in expression.finditer(text)]
        return {"valida": True, "cumple": bool(matches), "coincidencias": matches, "error": None}
