"""Seguimiento protegido de los procesos aprobados en la entrega 3."""

import base64
import binascii
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from app.api.dependencies.auditoria import audit_exports
from app.api.dependencies.operacion import operations_monitor
from app.core.identity import Principal, require
from app.modules.auditoria.application.export import AuditExports
from app.modules.operacion.application.monitor import MONITORED_PROCESS_TYPES, OperationsMonitor

router = APIRouter(prefix="/api/v1/procesos", tags=["Procesos"])


def _decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), int) or raw["id"] < 1 or not isinstance(raw.get("creado_en"), str):
            raise ValueError
        created_at = datetime.fromisoformat(raw["creado_en"])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, raw["id"]
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(400, "Cursor de procesos inválido") from None


@router.get("")
def listar(
    response: Response,
    tipo: str | None = None,
    estado: str | None = None,
    modo: str | None = None,
    medicion_id: int | None = Query(None, ge=1),
    cursor: str | None = None,
    limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("procesos:ver")),
    monitor: OperationsMonitor = Depends(operations_monitor),
):
    visible_types = tuple(kind for kind, permission in (
        ("correo_acceso", "usuarios:editar"), ("exportacion", "auditoria:ver"),
        ("preparar_medicion", "mediciones:ver"), ("carga_scraper", "mediciones:ver"),
    ) if permission in principal.permissions)
    after = _decode_cursor(cursor)
    rows = monitor.processes(
        principal.user["id"],
        {"tipo": tipo, "estado": estado, "modo": modo, "medicion_id": medicion_id},
        after, limite, visible_types,
    )
    if len(rows) > limite:
        rows = rows[:limite]
        last = rows[-1]
        token = json.dumps({"creado_en": last["creado_en"].isoformat(), "id": last["id"]}, separators=(",", ":")).encode()
        response.headers["X-Next-Cursor"] = base64.urlsafe_b64encode(token).decode().rstrip("=")
    return rows


@router.get("/estadisticas")
def estadisticas(
    principal: Principal = Depends(require("procesos:ver")),
    monitor: OperationsMonitor = Depends(operations_monitor),
):
    visible_types = tuple(kind for kind, permission in (
        ("correo_acceso", "usuarios:editar"), ("exportacion", "auditoria:ver"),
        ("preparar_medicion", "mediciones:ver"), ("carga_scraper", "mediciones:ver"),
    ) if permission in principal.permissions)
    return monitor.process_statistics(principal.user["id"], visible_types)


@router.get("/{id}")
def ver(id: int, principal: Principal = Depends(require("procesos:ver")),
        exports: AuditExports = Depends(audit_exports),
        monitor: OperationsMonitor = Depends(operations_monitor)):
    row = exports.store.get(id)
    if row is None or row["creado_por"] != principal.user["id"]:
        raise HTTPException(404, "Proceso no encontrado")
    if row["tipo"] == "preparar_medicion":
        visible_types = ("preparar_medicion",) if "mediciones:ver" in principal.permissions else ()
        detail = monitor.process_detail(id, principal.user["id"], visible_types,
                                        bool(principal.role["ver_todas"]))
        if detail is None:
            raise HTTPException(404, "Proceso no encontrado")
        return {key: row[key] for key in (
            "id", "tipo", "estado", "creado_en", "iniciado_en", "finalizado_en", "progreso",
            "total", "procesados", "ok", "errores",
        )}
    if row["tipo"] == "exportacion" and row["opciones"].get("kind") == "auditoria":
        if "auditoria:ver" not in principal.permissions:
            raise HTTPException(403, "Permiso insuficiente para Auditoría")
    elif row["tipo"] == "correo_acceso":
        if "usuarios:editar" not in principal.permissions:
            raise HTTPException(403, "Permiso insuficiente para Usuarios")
    else:
        raise HTTPException(404, "Proceso no disponible en esta entrega")
    return row


@router.get("/{id}/tareas")
def tareas(id: int, principal: Principal = Depends(require("procesos:ver")),
           monitor: OperationsMonitor = Depends(operations_monitor)):
    detail = monitor.process_detail(id, principal.user["id"], MONITORED_PROCESS_TYPES,
                                    bool(principal.role["ver_todas"]))
    if detail is None:
        raise HTTPException(404, "Proceso no encontrado")
    process, task_rows = detail
    if process["tipo"] == "exportacion" and "auditoria:ver" not in principal.permissions:
        raise HTTPException(403, "Permiso insuficiente para Auditoría")
    if process["tipo"] == "correo_acceso" and "usuarios:editar" not in principal.permissions:
        raise HTTPException(403, "Permiso insuficiente para Usuarios")
    if process["tipo"] == "preparar_medicion" and "mediciones:ver" not in principal.permissions:
        raise HTTPException(403, "Permiso insuficiente para Mediciones")
    return task_rows
