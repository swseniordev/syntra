"""Presentación configurable del correo; los secretos se reciben solo al renderizar."""

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import re


_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_DEFAULT_LOGO = Path(__file__).resolve().parents[2] / "frontend" / "public" / "brand" / "symbol.png"


@dataclass(frozen=True)
class MailTemplate:
    logo_file: Path
    primary_color: str = "#1458D4"
    background_color: str = "#F5F8FF"
    text_color: str = "#172442"
    title_initial: str = "Bienvenido a Syntra"
    title_reset: str = "Nueva contraseña de Syntra"
    intro_initial: str = "Se creó tu acceso a Syntra. Usa estos datos para ingresar:"
    intro_reset: str = "Se generó una nueva contraseña para tu acceso a Syntra:"
    footer: str = "Ingresa únicamente desde la dirección oficial de Syntra."

    @classmethod
    def from_file(cls, path: Path | None = None) -> "MailTemplate":
        values = {} if path is None else json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("La plantilla de correo debe ser un objeto JSON")
        allowed = {field for field in cls.__dataclass_fields__}
        if set(values) - allowed:
            raise ValueError("La plantilla de correo contiene campos desconocidos")
        logo = Path(values.pop("logo_file", _DEFAULT_LOGO))
        if not logo.is_absolute() and path is not None:
            logo = path.parent / logo
        if not logo.is_file() or logo.suffix.lower() != ".png":
            raise ValueError("El logotipo de correo debe ser un archivo PNG aprobado y disponible")
        for key, value in values.items():
            if not isinstance(value, str) or len(value) > 500:
                raise ValueError("Valor inválido en la plantilla de correo")
            if key.endswith("_color") and not _COLOR.fullmatch(value):
                raise ValueError("Los colores del correo deben tener formato hexadecimal #RRGGBB")
        return cls(logo_file=logo, **values)

    def render(self, recipient: str, password: str, reason: str) -> tuple[str, str, str]:
        reset = reason == "reenvio"
        title = self.title_reset if reset else self.title_initial
        intro = self.intro_reset if reset else self.intro_initial
        plain = (f"{title}\n\n{intro}\n\nCorreo de acceso a Syntra: {recipient}\n"
                 f"Contraseña temporal: {password}\n\n{self.footer}\n")
        html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:{self.background_color};color:{self.text_color};font-family:Arial,sans-serif">
<table role="presentation" style="width:100%;max-width:540px;margin:auto;border-collapse:collapse;background:#ffffff;border-radius:12px">
<tr><td style="padding:28px"><img src="cid:syntra-logo" width="56" height="72" alt="Syntra" style="display:block;width:56px;height:auto;margin-bottom:22px">
<h1 style="font-size:23px;line-height:1.3;color:{self.primary_color};margin:0 0 14px">{escape(title)}</h1>
<p style="line-height:1.6">{escape(intro)}</p>
<p style="line-height:1.6"><strong>Correo de acceso:</strong> {escape(recipient)}</p>
<p style="line-height:1.6"><strong>Contraseña temporal:</strong> <span style="font-family:monospace;overflow-wrap:anywhere">{escape(password)}</span></p>
<p style="font-size:13px;line-height:1.6;color:{self.text_color}">{escape(self.footer)}</p>
</td></tr></table></body></html>"""
        return title, plain, html
