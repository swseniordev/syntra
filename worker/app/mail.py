"""Proveedor SMTP STARTTLS. El texto plano solo existe en memoria durante el envío."""

from email.message import EmailMessage
from pathlib import Path
import smtplib
import ssl

from app.mail_template import MailTemplate


class MailProviderError(RuntimeError):
    pass


class StartTlsMailProvider:
    def __init__(self, host: str, port: int, user: str, password_file: Path, sender: str,
                 template: MailTemplate | None = None):
        self.host, self.port, self.user = host, port, user
        self.password_file, self.sender = password_file, sender
        self.template = template or MailTemplate.from_file()

    def send_password(self, recipient: str, password: str, timeout: float, reason: str = "alta") -> None:
        if not self.host or not self.sender or not self.user or not self.password_file.is_file():
            raise MailProviderError("El proveedor de correo no está configurado")
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        title, plain, html = self.template.render(recipient, password, reason)
        message["Subject"] = title
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
        html_part = message.get_body(preferencelist=("html",))
        assert html_part is not None
        html_part.add_related(self.template.logo_file.read_bytes(), maintype="image", subtype="png", cid="<syntra-logo>", filename="syntra.png")
        try:
            with smtplib.SMTP(self.host, self.port, timeout=timeout) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(self.user, self.password_file.read_text(encoding="utf-8").strip())
                server.send_message(message)
        except (OSError, smtplib.SMTPException):
            raise MailProviderError("El proveedor de correo rechazó o interrumpió el envío") from None
