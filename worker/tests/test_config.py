import os
import threading
import unittest
from unittest.mock import patch

from app.config import WorkerSettings
from app.main import run


class WorkerSettingsTests(unittest.TestCase):
    def test_concurrency_is_read_from_environment(self) -> None:
        with patch.dict(os.environ, {"SYNTRA_WORKER_CONCURRENCY": "7"}):
            self.assertEqual(WorkerSettings.from_environment().concurrency, 7)

    def test_invalid_concurrency_is_rejected(self) -> None:
        for value in ("0", "-2", "many"):
            with self.subTest(value=value), patch.dict(os.environ, {"SYNTRA_WORKER_CONCURRENCY": value}):
                with self.assertRaises(ValueError):
                    WorkerSettings.from_environment()

    def test_missing_concurrency_is_rejected(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("SYNTRA_WORKER_CONCURRENCY", None)
            with self.assertRaises(ValueError):
                WorkerSettings.from_environment()

    def test_measurement_queue_uses_dedicated_login_identity(self) -> None:
        with patch.dict(os.environ, {"SYNTRA_WORKER_CONCURRENCY": "2",
                                     "SYNTRA_WORKER_QUEUE": "q.mantenimiento"}, clear=True):
            settings = WorkerSettings.from_environment()
        self.assertEqual(settings.database_user, "syntra_measurement_worker_login")
        self.assertEqual(settings.database_passfile.name, "syntra_measurement_pgpass.conf")

    def test_worker_polls_injected_queue_and_shuts_down(self) -> None:
        class EmptyQueue:
            def recover(self):
                return 0

            def claim(self, *_args):
                return None

        class FakeRegistry:
            def __init__(self) -> None:
                self.registered = False
                self.stopped = False

            def register(self, *_args):
                self.registered = True

            def heartbeat(self, *_args):
                pass

            def unregister(self, *_args):
                self.stopped = True

        queue = EmptyQueue()
        registry = FakeRegistry()
        stop = threading.Event()
        thread = threading.Thread(target=run, args=(stop, queue, registry), daemon=True)

        with patch.dict(os.environ, {"SYNTRA_WORKER_CONCURRENCY": "2"}):
            thread.start()
            try:
                self.assertTrue(thread.is_alive())
                stop.set()
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
                self.assertTrue(registry.registered)
                self.assertTrue(registry.stopped)
            finally:
                stop.set()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
