"""Reglas y casos de uso sin PostgreSQL ni proveedor real."""

import ast
from pathlib import Path
from threading import Event
import logging
from types import SimpleNamespace

from app.application.export_report import ExportAuditReport
from app.application.runner import run_consumer
from app.application.send_access_mail import SendAccessMail
from app.domain.tasks import AuditReportRequest, ClaimedTask, mail_user_eligible, retry_delay_ms


def test_domain_and_application_do_not_import_infrastructure():
    root = Path(__file__).resolve().parents[1] / "app"
    forbidden = ("app.infrastructure", "app.queue", "app.reports", "app.mail", "psycopg", "openpyxl", "smtplib", "fastapi")
    for layer in ("domain", "application"):
        for source in (root / layer).glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            assert not any(name.startswith(forbidden) for name in imports), source


def test_domain_rules_are_pure():
    assert retry_delay_ms(1, 3, 100, 1000) == 100
    assert retry_delay_ms(2, 3, 100, 1000) == 200
    assert retry_delay_ms(3, 3, 100, 1000) is None
    assert mail_user_eligible({"estado_id": 1, "version_token": 4}, 4)
    assert not mail_user_eligible({"estado_id": 0, "version_token": 4}, 4)
    assert AuditReportRequest.from_options({"kind": "auditoria", "filters": {}, "corte": "2026-10-21T00:00:00+00:00"}).filters == {}


class FakeReport:
    def __init__(self, fail=False):
        self.calls = []
        self.raise_render = fail

    def load(self, task):
        self.calls.append("load")
        return AuditReportRequest({}, "2026-10-21T00:00:00+00:00"), 1000

    def render(self, task, request, deadline):
        self.calls.append("render")
        if self.raise_render:
            raise OSError("fallo del disco")
        return 2, object()

    def publish(self, task, worker_id, count, staged):
        self.calls.append("publish")
        return True

    def refresh_lease(self, task, worker_id):
        return True

    def fail(self, task, worker_id):
        self.calls.append("fail")


def test_export_case_coordinates_success_and_failure_without_database():
    task = ClaimedTask(1, 2, 1, {})
    success = FakeReport()
    ExportAuditReport(success).execute(task, "worker")
    assert success.calls == ["load", "render", "publish"]
    failure = FakeReport(fail=True)
    ExportAuditReport(failure).execute(task, "worker")
    assert failure.calls == ["load", "render", "fail"]


def test_export_deadline_prevents_publication():
    times = iter((0.0, 2.0))
    report = FakeReport()
    ExportAuditReport(report, clock=lambda: next(times)).execute(ClaimedTask(1, 2, 1, {}), "worker")
    assert report.calls == ["load", "render", "fail"]


def test_mail_case_uses_replaceable_provider():
    calls = []

    class Adapter:
        def prepare(self, task, worker_id): return ("recipient@example.test", "temporal", 1.0, "alta")
        def deliver(self, recipient, password, timeout, reason): calls.append("deliver")
        def complete(self, task, worker_id): calls.append("complete")
        def fail(self, task, worker_id): calls.append("fail")

    SendAccessMail(Adapter()).execute(ClaimedTask(1, 1, 1, {}), "worker")
    assert calls == ["deliver", "complete"]

    calls.clear()
    class Rejected(Adapter):
        def deliver(self, recipient, password, timeout, reason):
            calls.append("deliver")
            raise OSError("proveedor no disponible")
    SendAccessMail(Rejected()).execute(ClaimedTask(1, 1, 1, {}), "worker")
    assert calls == ["deliver", "fail"]


def test_runner_accepts_consumer_contract_without_concrete_queue():
    stop = Event()
    calls = []

    class Consumer:
        def recover(self): calls.append("recover"); return 0
        def claim(self, *_): calls.append("claim"); return ClaimedTask(1, 1, 1, {})
        def process(self, *_): calls.append("process"); stop.set()

    class Registry:
        def register(self, *_): calls.append("register")
        def heartbeat(self, *_): calls.append("heartbeat")
        def unregister(self, *_): calls.append("unregister")

    run_consumer(Consumer(), Registry(), "worker", "host", 1, 1, .01, stop, logging.getLogger("test"))
    assert calls[0] == "register" and calls[-1] == "unregister"
    assert "process" in calls and "recover" in calls


def test_mail_composition_starts_and_stops_without_smtp_or_database(tmp_path, monkeypatch):
    from app.config import WorkerSettings
    from app.main import run

    secret = tmp_path / "dummy-mail-secret"
    secret.write_text("solo-para-composicion", encoding="utf-8")
    settings = SimpleNamespace(
        queue="q.notificaciones", concurrency=1, log_level="INFO", poll_seconds=.01,
        smtp_host="localhost", smtp_port=587, smtp_user="trial@example.test",
        smtp_password_file=secret, smtp_from="trial@example.test",
        mail_template_file=Path(__file__).resolve().parents[1] / "mail_template.json",
    )
    monkeypatch.setattr(WorkerSettings, "from_environment", classmethod(lambda _cls: settings))
    calls = []

    class Registry:
        def register(self, *_): calls.append("register")
        def heartbeat(self, *_): calls.append("heartbeat")
        def unregister(self, *_): calls.append("unregister")

    stop = Event()
    stop.set()
    run(stop_event=stop, registry=Registry())
    assert calls == ["register", "unregister"]
