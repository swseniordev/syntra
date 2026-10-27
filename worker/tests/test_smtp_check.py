from pathlib import Path
from types import SimpleNamespace

from scripts import check_smtp


def test_smtp_check_authenticates_without_sending(monkeypatch, tmp_path: Path, capsys):
    password_file = tmp_path / "smtp_password"
    password_file.write_text("test-only-password", encoding="utf-8")
    settings = SimpleNamespace(queue="q.notificaciones", smtp_host="smtp.test", smtp_port=587,
                               smtp_user="sender@example.test", smtp_password_file=password_file)
    monkeypatch.setattr(check_smtp.WorkerSettings, "from_environment", lambda: settings)

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.test", 587, 15)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def ehlo(self):
            pass

        def starttls(self, context):
            assert context is not None

        def login(self, user, password):
            assert (user, password) == ("sender@example.test", "test-only-password")

        def noop(self):
            pass

    monkeypatch.setattr(check_smtp.smtplib, "SMTP", FakeSMTP)
    check_smtp.main()
    output = capsys.readouterr().out
    assert "no se envió correo" in output
    assert "test-only-password" not in output
