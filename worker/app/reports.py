"""Adaptador PostgreSQL de tareas de exportación de Auditoría."""

from datetime import datetime
from pathlib import Path

from psycopg.types.json import Jsonb

from app.config import WorkerSettings
from app.domain.tasks import AuditReportRequest, retry_delay_ms
from app.infrastructure.report_files import ReportFiles, private_root as _private_root, safe_cell as _safe_cell
from app.infrastructure.report_rows import audit_rows
from app.queue import ClaimedTask, TaskQueue


class ReportQueue(TaskQueue):
    def __init__(self, settings: WorkerSettings, connect=None):
        super().__init__(settings, "q.reportes", "auditoria_exportar", "auditoria_exportar", connect)
        self.root = _private_root(settings.report_root)
        self.files = ReportFiles(self.root)

    def _path(self, process_id: int, extension: str) -> Path:
        return self.files.path(process_id, extension)

    def _rows(self, conn, filters: dict, cutoff: datetime):
        yield from audit_rows(conn, filters, cutoff)

    def _write(self, process_id: int, filters: dict, cutoff: datetime,
               staged_path: Path | None = None, deadline: float | None = None):
        with self._connect() as conn:
            return self.files.write(process_id, self._rows(conn, filters, cutoff), staged_path, deadline)

    def load(self, task: ClaimedTask) -> tuple[AuditReportRequest, int]:
        with self._connect() as conn:
            process = conn.execute("SELECT opciones FROM prc.proceso WHERE id=%s", (task.process_id,)).fetchone()
            policy = self.policy(conn)
        request = AuditReportRequest.from_options(process["opciones"] if process else {})
        return request, policy["timeout_ms"]

    def render(self, task: ClaimedTask, request: AuditReportRequest,
               deadline: float) -> tuple[int, Path | None]:
        cutoff = datetime.fromisoformat(request.cutoff)
        if cutoff.tzinfo is None:
            raise ValueError("Corte sin zona horaria")
        return self._write(task.process_id, request.filters, cutoff,
                           self.files.unique_temp(task.process_id), deadline)

    def publish(self, task: ClaimedTask, worker_id: str, count: int, staged: Path | None) -> bool:
        with self._connect() as conn:
            owned = conn.execute(
                "SELECT id FROM prc.proceso_tarea WHERE id=%s AND worker=%s "
                "AND estado='en_ejecucion' FOR UPDATE", (task.id, worker_id),
            ).fetchone()
            if not owned:
                if staged is not None:
                    staged.unlink(missing_ok=True)
                return False
            final = self.files.publish(task.process_id, staged)
            self._finish(conn, task, worker_id, "completado")
            conn.execute("UPDATE prc.proceso SET total=%s,procesados=%s,ok=%s,stats=%s "
                         "WHERE id=%s AND estado='completado'",
                         (count, count, count, Jsonb({"filas": count, "archivo": final.name}), task.process_id))
        return True

    def refresh_lease(self, task: ClaimedTask, worker_id: str) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE prc.proceso_tarea SET latido=now() WHERE id=%s AND worker=%s "
                "AND estado='en_ejecucion' RETURNING id", (task.id, worker_id),
            ).fetchone()
        return bool(changed)

    def _failure(self, task: ClaimedTask, worker_id: str) -> None:
        with self._connect() as conn:
            policy = self.policy(conn)
            locked = conn.execute(
                "SELECT id FROM prc.proceso_tarea WHERE id=%s AND worker=%s AND estado='en_ejecucion' FOR UPDATE",
                (task.id, worker_id),
            ).fetchone()
            if not locked:
                return
            wait_ms = retry_delay_ms(task.attempts, policy["max_intentos"],
                                     policy["backoff_base_ms"], policy["backoff_max_ms"])
            if wait_ms is not None:
                conn.execute("UPDATE prc.proceso_tarea SET estado='en_cola',worker=NULL,"
                             "disponible_en=now()+(%s*interval '1 millisecond'),error_codigo='exportacion_fallida',"
                             "error_mensaje='No se pudo generar el archivo' WHERE id=%s", (wait_ms, task.id))
                conn.execute("UPDATE prc.proceso SET estado='en_cola',errores=errores+1,"
                             "detalle='exportacion_fallida' WHERE id=%s", (task.process_id,))
            else:
                self._finish(conn, task, worker_id, "error", "exportacion_fallida")

    def fail(self, task: ClaimedTask, worker_id: str) -> None:
        self._failure(task, worker_id)

    def process(self, task: ClaimedTask, worker_id: str) -> None:
        from app.application.export_report import ExportAuditReport
        ExportAuditReport(self).execute(task, worker_id)

    def cleanup(self) -> tuple[int, int]:
        return self.files.cleanup()
