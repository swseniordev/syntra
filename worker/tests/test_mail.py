from pathlib import Path

from app.mail import MailProviderError, StartTlsMailProvider
from app.mail_template import MailTemplate


def test_access_email_identifies_login_address(monkeypatch, tmp_path: Path):
    secret = tmp_path / "password"
    secret.write_text("test-smtp-key", encoding="utf-8")
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.test", 587, 5)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def ehlo(self):
            pass

        def starttls(self, context):
            assert context is not None

        def login(self, user, password):
            assert (user, password) == ("sender@example.test", "test-smtp-key")

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("app.mail.smtplib.SMTP", FakeSMTP)
    provider = StartTlsMailProvider("smtp.test", 587, "sender@example.test", secret, "sender@example.test")
    provider.send_password("recipient@example.test", "test-temporary-password", 5)
    assert len(sent) == 1
    body = sent[0].get_body(preferencelist=("plain",)).get_content()
    assert "Correo de acceso a Syntra: recipient@example.test" in body
    assert "Contraseña temporal: test-temporary-password" in body
    html = sent[0].get_body(preferencelist=("html",)).get_content()
    assert "cid:syntra-logo" in html
    assert any(part.get_content_type() == "image/png" for part in sent[0].walk())


def test_template_escapes_inserted_values_and_uses_reset_copy():
    template = MailTemplate.from_file()
    title, plain, html = template.render("<user>@example.test", "a<b&c", "reenvio")
    assert title == "Nueva contraseña de Syntra"
    assert "a<b&c" in plain
    assert "a&lt;b&amp;c" in html
    assert "&lt;user&gt;@example.test" in html


def test_external_template_changes_copy_and_colors_without_secrets(tmp_path: Path):
    import json
    config = tmp_path / "mail.json"
    config.write_text(json.dumps({"primary_color": "#123ABC", "title_initial": "Acceso configurado"}), encoding="utf-8")
    template = MailTemplate.from_file(config)
    title, plain, html = template.render("user@example.test", "temporary-test-value", "alta")
    assert title == "Acceso configurado" and title in plain
    assert "#123ABC" in html
    assert "temporary-test-value" not in config.read_text(encoding="utf-8")


def test_template_rejects_missing_logo_and_invalid_color(tmp_path: Path):
    import json
    import pytest
    config = tmp_path / "mail.json"
    config.write_text(json.dumps({"logo_file": str(tmp_path / "missing.png")}), encoding="utf-8")
    with pytest.raises(ValueError, match="logotipo"):
        MailTemplate.from_file(config)
    config.write_text(json.dumps({"primary_color": "red"}), encoding="utf-8")
    with pytest.raises(ValueError, match="colores"):
        MailTemplate.from_file(config)


def test_smtp_failure_is_reported_without_secret_in_message(monkeypatch, tmp_path: Path):
    import pytest
    import smtplib
    secret = tmp_path / "password"
    secret.write_text("private-test-value", encoding="utf-8")

    class FailingSMTP:
        def __init__(self, *_args, **_kwargs):
            raise smtplib.SMTPException("private-test-value")

    monkeypatch.setattr("app.mail.smtplib.SMTP", FailingSMTP)
    provider = StartTlsMailProvider("smtp.test", 587, "sender@example.test", secret, "sender@example.test")
    with pytest.raises(MailProviderError) as caught:
        provider.send_password("recipient@example.test", "temporary-test-value", 5)
    assert "private-test-value" not in str(caught.value)
    assert "temporary-test-value" not in str(caught.value)
