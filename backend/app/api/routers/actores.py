"""HTTP de Actores de Apify: permisos, contrato, ETag y errores."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auditoria import audit_use_cases
from app.api.dependencies.actores import actor_use_cases
from app.core.identity import Principal, require
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor
from app.modules.actores.application.service import (ActorProblem, ActorProblemKind, ActorUseCases, version_tag)

router = APIRouter(prefix="/api/v1/actores", tags=["Actores"])
T = TypeVar("T")
HTTP_STATUS = {
    ActorProblemKind.VALIDATION: 400,
    ActorProblemKind.NOT_FOUND: 404,
    ActorProblemKind.CONFLICT: 409,
    ActorProblemKind.PRECONDITION_REQUIRED: 428,
    ActorProblemKind.PRECONDITION_FAILED: 412,
}

Red = Literal["x", "tiktok", "youtube", "facebook", "instagram"]
Uso = Literal["busqueda", "metricas", "perfil"]
ACTOR_PATTERN = r"^[\w.-]+/[\w.-]+$"


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ActorProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class ActorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    red: Red
    uso: Uso = "busqueda"
    nombre: str = Field(min_length=1)
    actor: str = Field(pattern=ACTOR_PATTERN)
    max_registros: int = Field(default=1000, ge=1)
    max_urls_por_corrida: int = Field(default=1000, ge=1)
    memoria_mb: int = Field(default=4096, ge=1)
    nota: str | None = None
    estado_id: Literal[0, 1] = 1


class ActorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    red: Red | None = None
    uso: Uso | None = None
    nombre: str | None = Field(default=None, min_length=1)
    actor: str | None = Field(default=None, pattern=ACTOR_PATTERN)
    max_registros: int | None = Field(default=None, ge=1)
    max_urls_por_corrida: int | None = Field(default=None, ge=1)
    memoria_mb: int | None = Field(default=None, ge=1)
    nota: str | None = None
    estado_id: Literal[0, 1] | None = None


class ActorEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("actores:ver")),
    cases: ActorUseCases = Depends(actor_use_cases),
):
    return _run(lambda: cases.list(q, estado, orden, cursor, limite))


@router.get("/{id}/historial")
def historial(
    id: int, response: Response, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    try:
        items, following = cases.history("Actor", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.post("", status_code=201)
def crear(
    body: ActorIn, response: Response,
    principal: Principal = Depends(require("actores:crear")),
    cases: ActorUseCases = Depends(actor_use_cases),
):
    row = _run(lambda: cases.create(body.model_dump(), principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/actores/{row['id']}"
    return row


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("actores:ver")),
    cases: ActorUseCases = Depends(actor_use_cases),
):
    row = _run(lambda: cases.get(id))
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(
    id: int, body: ActorPatch, response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("actores:editar")),
    cases: ActorUseCases = Depends(actor_use_cases),
):
    changes = body.model_dump(exclude_unset=True)
    if any(value is None for key, value in changes.items() if key != "nota"):
        raise HTTPException(400, "Este campo no admite null")
    row = _run(lambda: cases.edit(id, changes, if_match, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int, principal: Principal = Depends(require("actores:eliminar")),
    cases: ActorUseCases = Depends(actor_use_cases),
):
    _run(lambda: cases.delete(id, principal.user["id"]))
    return Response(status_code=204)


@router.post("/{id}/restaurar")
def restaurar(
    id: int, response: Response,
    principal: Principal = Depends(require("actores:eliminar")),
    cases: ActorUseCases = Depends(actor_use_cases),
):
    row = _run(lambda: cases.restore(id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(
    id: int, body: ActorEstado, response: Response,
    principal: Principal = Depends(require("actores:editar")),
    cases: ActorUseCases = Depends(actor_use_cases),
):
    row = _run(lambda: cases.change_state(id, body.estado_id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row
