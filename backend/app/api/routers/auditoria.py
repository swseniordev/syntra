"""Lectura protegida del registro funcional de Auditoría."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auditoria import audit_exports, audit_use_cases
from app.core.config import settings
from app.core.identity import Principal, require
from app.core.security import sign_audit_download, verify_audit_download
from app.modules.auditoria.application.export import AuditExports, ExportProblem, ExportProblemKind
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor

router = APIRouter(prefix="/api/v1/auditoria", tags=["Auditoría"])
STATUS = {ExportProblemKind.VALIDATION: 400, ExportProblemKind.FORBIDDEN: 403,
          ExportProblemKind.NOT_FOUND: 404, ExportProblemKind.CONFLICT: 409,
          ExportProblemKind.PENDING: 409, ExportProblemKind.GONE: 410}


def _export_file(process_id: int) -> Path:
    root = settings.report_root
    if (not root.is_absolute() or root.is_symlink() or
            root.resolve(strict=False).is_relative_to(Path(__file__).resolve().parents[4])):
        raise HTTPException(503, "Almacenamiento privado no disponible")
    file = root / f"auditoria-{process_id}.xlsx"
    if file.is_symlink() or not file.is_file() or file.resolve().parent != root.resolve():
        raise HTTPException(404, "Archivo de exportación no encontrado")
    return file


def _ready(process_id: int, actor_id: int, exports: AuditExports) -> dict:
    try:
        process = exports.owned(process_id, actor_id)
    except ExportProblem as exc:
        raise HTTPException(STATUS[exc.kind], exc.detail) from exc
    if process["estado"] != "completado":
        raise HTTPException(409, "La exportación aún no está disponible")
    finished = process["finalizado_en"]
    if finished is None or datetime.now(timezone.utc) > finished + timedelta(days=7):
        raise HTTPException(410, "El archivo de exportación ya venció")
    return process


class AuditExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modulo: str | None = None
    usuario_id: int | None = Field(default=None, ge=1)
    accion: str | None = None
    entidad_tipo: str | None = None
    entidad_id: str | None = None
    desde: datetime | None = None
    hasta: datetime | None = None
    q: str | None = None


@router.get("")
def listar(
    modulo: str | None = None, usuario_id: int | None = Query(None, ge=1),
    accion: str | None = None, entidad_tipo: str | None = None, entidad_id: str | None = None,
    desde: datetime | None = None, hasta: datetime | None = None, q: str | None = None,
    cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    for date in (desde, hasta):
        if date is not None and date.tzinfo is None:
            raise HTTPException(400, "Las fechas deben incluir zona horaria")
    filters = {"modulo": modulo, "usuario_id": usuario_id, "accion": accion,
               "entidad_tipo": entidad_tipo, "entidad_id": entidad_id,
               "desde": desde, "hasta": hasta, "q": q.strip() if q else None}
    try:
        return cases.list(filters, cursor, limite)
    except (InvalidAuditCursor, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/exportar", status_code=202)
def exportar(body: AuditExportIn, response: Response,
             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
             principal: Principal = Depends(require("auditoria:ver")),
             exports: AuditExports = Depends(audit_exports)):
    values = body.model_dump()
    if values.get("q") is not None:
        values["q"] = values["q"].strip() or None
    try:
        accepted = exports.enqueue(principal.user["id"], idempotency_key, values)
    except ExportProblem as exc:
        raise HTTPException(STATUS[exc.kind], exc.detail) from exc
    response.headers["Location"] = f"/api/v1/procesos/{accepted['proceso_id']}"
    response.headers["Cache-Control"] = "no-store"
    return accepted


@router.get("/resumen")
def resumen(
    desde: datetime = Query(...), hasta: datetime = Query(...),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    try:
        return cases.summary(desde, hasta)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/exportaciones/{proceso_id}/descarga")
def enlace_descarga(proceso_id: int, response: Response,
                    principal: Principal = Depends(require("auditoria:ver")),
                    exports: AuditExports = Depends(audit_exports)):
    _ready(proceso_id, principal.user["id"], exports)
    _export_file(proceso_id)
    token = sign_audit_download(principal.user["id"], principal.session_id, proceso_id)
    path = f"/api/v1/auditoria/exportaciones/{proceso_id}/archivo"
    response.set_cookie(key=f"syntra_audit_dl_{proceso_id}", value=token,
                        max_age=900, path=path, secure=True, httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return {"url": path,
            "expira_en": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}


@router.get("/exportaciones/{proceso_id}/archivo")
def archivo(proceso_id: int, request: Request,
            principal: Principal = Depends(require("auditoria:ver")),
            exports: AuditExports = Depends(audit_exports)):
    token = request.cookies.get(f"syntra_audit_dl_{proceso_id}", "")
    if not verify_audit_download(token, principal.user["id"], principal.session_id, proceso_id):
        raise HTTPException(403, "Enlace de descarga inválido o vencido")
    _ready(proceso_id, principal.user["id"], exports)
    file = _export_file(proceso_id)
    return FileResponse(file, filename=file.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})


@router.get("/{id}")
def ver(
    id: int, fecha: datetime = Query(...),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    try:
        row = cases.get(id, fecha)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "Evento de auditoría no encontrado")
    return row
