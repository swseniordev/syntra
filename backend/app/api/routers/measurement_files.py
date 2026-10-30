"""HTTP de archivos de Mediciones: autenticación, validación y traducción de errores."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.db import connection
from app.core.identity import Principal, require
from app.core.security import sign_measurement_file_download, verify_measurement_file_download
from app.modules.mediciones.application.file_service import FileProblem, MeasurementFileUseCases
from app.modules.mediciones.infrastructure.file_postgres import PostgresMeasurementFileRepository
from app.modules.mediciones.infrastructure.local_storage import LocalObjectStore


router = APIRouter(prefix="/api/v1", tags=["Cargas"])


class PresignarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(min_length=1, max_length=255)
    tamano_bytes: int = Field(gt=0, le=50 * 1024 * 1024)
    formato_id: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class CargaArchivosIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archivo_ids: list[int] = Field(min_length=1, max_length=100)
    al_incorporar: dict[str, bool] | None = None
    modo: Literal["upsert", "reemplazar"] = "upsert"


def use_cases(conn: psycopg.Connection = Depends(connection)) -> MeasurementFileUseCases:
    return MeasurementFileUseCases(PostgresMeasurementFileRepository(conn),
                                   LocalObjectStore(settings.upload_root))


def _global(principal: Principal) -> bool:
    return bool(principal.role["ver_todas"])


def _translate(problem: FileProblem) -> None:
    raise HTTPException(problem.status, problem.detail) from problem


@router.post("/mediciones/{id}/archivos/presignar", status_code=201)
def reservar_archivo(id: int, body: PresignarIn,
                     principal: Principal = Depends(require("mediciones:ejecutar")),
                     cases: MeasurementFileUseCases = Depends(use_cases)):
    try:
        return cases.reserve(id, body.nombre, body.tamano_bytes, body.formato_id,
                             principal.user["id"], _global(principal), body.sha256)
    except FileProblem as exc:
        _translate(exc)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, "El archivo ya existe en esta medición") from exc


@router.put("/archivos/{id}/contenido", status_code=204)
async def cargar_contenido(id: int, request: Request,
                          principal: Principal = Depends(require("mediciones:ejecutar")),
                          cases: MeasurementFileUseCases = Depends(use_cases)):
    try:
        await cases.upload(id, request.stream(), principal.user["id"], _global(principal))
    except FileProblem as exc:
        _translate(exc)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, "El archivo ya existe en esta medición") from exc
    return Response(status_code=204)


@router.get("/mediciones/{id}/archivos")
def listar_archivos(id: int, response: Response, limite: int = Query(25, ge=1, le=200),
                    cursor: str | None = Query(None),
                    principal: Principal = Depends(require("mediciones:ver")),
                    cases: MeasurementFileUseCases = Depends(use_cases)):
    try:
        items, next_cursor = cases.list(id, limite, principal.user["id"],
                                        _global(principal), cursor)
        if next_cursor:
            response.headers["X-Next-Cursor"] = next_cursor
        return items
    except FileProblem as exc:
        _translate(exc)


@router.get("/mediciones/{id}/lotes")
def listar_lotes(id: int, response: Response, limite: int = Query(25, ge=1, le=200),
                 cursor: str | None = Query(None), origen: str | None = Query(None),
                 principal: Principal = Depends(require("mediciones:ver")),
                 cases: MeasurementFileUseCases = Depends(use_cases)):
    try:
        items, next_cursor = cases.lots(id, limite, principal.user["id"],
                                        _global(principal), cursor, origen)
        if next_cursor:
            response.headers["X-Next-Cursor"] = next_cursor
        return items
    except FileProblem as exc:
        _translate(exc)


@router.post("/mediciones/{id}/cargas/archivos", status_code=202)
def encolar_archivos(id: int, body: CargaArchivosIn,
                     idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
                     principal: Principal = Depends(require("mediciones:ejecutar")),
                     cases: MeasurementFileUseCases = Depends(use_cases)):
    try:
        return cases.enqueue(id, body.archivo_ids, principal.user["id"], _global(principal),
                             idempotency_key, body.al_incorporar, body.modo)
    except FileProblem as exc:
        _translate(exc)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, "La clave de idempotencia ya fue utilizada") from exc


@router.get("/archivos/{id}/contenido")
def descargar_contenido(id: int, request: Request,
                        principal: Principal = Depends(require("mediciones:ver")),
                        cases: MeasurementFileUseCases = Depends(use_cases)):
    token = request.cookies.get(f"syntra_med_file_dl_{id}", "")
    if not verify_measurement_file_download(token, principal.user["id"], principal.session_id, id):
        raise HTTPException(403, "Enlace de descarga inválido o vencido")
    try:
        row, path = cases.get_download(id, principal.user["id"], _global(principal))
    except FileProblem as exc:
        _translate(exc)
    return FileResponse(path, filename=row["nombre"], media_type="application/octet-stream",
                        headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})


@router.get("/archivos/{id}/descargar")
def obtener_descarga(id: int, response: Response,
                      principal: Principal = Depends(require("mediciones:ver")),
                      cases: MeasurementFileUseCases = Depends(use_cases)):
    try:
        cases.get_download(id, principal.user["id"], _global(principal))
    except FileProblem as exc:
        _translate(exc)
    path = f"/api/v1/archivos/{id}/contenido"
    response.set_cookie(key=f"syntra_med_file_dl_{id}",
                        value=sign_measurement_file_download(principal.user["id"], principal.session_id, id),
                        max_age=900, path=path, secure=True, httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return {"url": path,
            "expira_en": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}
