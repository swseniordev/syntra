"""Contrato HTTP de Prompts con seguridad y concurrencia optimista."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auditoria import audit_use_cases
from app.api.dependencies.prompts import prompt_use_cases
from app.core.identity import Principal, require
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor
from app.modules.prompts.application.service import PromptProblem, PromptProblemKind, PromptUseCases, version_tag

router = APIRouter(prefix="/api/v1/prompts", tags=["Prompts"])
T = TypeVar("T")
Kind = Literal["cluster", "temas", "relevancia", "sentimiento", "etiqueta_cluster"]
Network = Literal["x", "tiktok", "youtube", "facebook", "instagram", "medios"]
HTTP_STATUS = {
    PromptProblemKind.VALIDATION: 400,
    PromptProblemKind.NOT_FOUND: 404,
    PromptProblemKind.CONFLICT: 409,
    PromptProblemKind.PRECONDITION_REQUIRED: 428,
    PromptProblemKind.PRECONDITION_FAILED: 412,
}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except PromptProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class PromptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: Kind
    red: Network | None = None
    nombre: str = Field(min_length=1)
    contenido: str = Field(min_length=1)
    por_defecto: bool = False
    estado_id: Literal[0, 1] = 1


class PromptPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: Kind | None = None
    red: Network | None = None
    nombre: str | None = None
    contenido: str | None = None
    por_defecto: bool | None = None
    estado_id: Literal[0, 1] | None = None


class PromptEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, tipo: str | None = None, red: str | None = None,
    cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("prompts:ver")),
    cases: PromptUseCases = Depends(prompt_use_cases),
):
    return _run(lambda: cases.list(q, estado, orden, tipo, red, cursor, limite))


@router.get("/{id}/historial")
def historial(
    id: int, response: Response, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    try:
        items, following = cases.history("Prompt", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.get("/{id}/versiones")
def versiones(
    id: int, principal: Principal = Depends(require("prompts:ver")),
    cases: PromptUseCases = Depends(prompt_use_cases),
):
    return _run(lambda: cases.versions(id))


@router.post("", status_code=201)
def crear(
    body: PromptIn, response: Response,
    principal: Principal = Depends(require("prompts:crear")),
    cases: PromptUseCases = Depends(prompt_use_cases),
):
    row = _run(lambda: cases.create(body.model_dump(), principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/prompts/{row['id']}"
    return row


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("prompts:ver")),
    cases: PromptUseCases = Depends(prompt_use_cases),
):
    row = _run(lambda: cases.get(id))
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(
    id: int, body: PromptPatch, response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("prompts:editar")),
    cases: PromptUseCases = Depends(prompt_use_cases),
):
    changes = body.model_dump(exclude_unset=True)
    if any(changes[field] is None for field in ("tipo", "nombre", "contenido", "por_defecto", "estado_id") if field in changes):
        raise HTTPException(400, "Este campo no admite null")
    row = _run(lambda: cases.edit(id, changes, if_match, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int, principal: Principal = Depends(require("prompts:eliminar")),
    cases: PromptUseCases = Depends(prompt_use_cases),
):
    _run(lambda: cases.delete(id, principal.user["id"]))
    return Response(status_code=204)


@router.post("/{id}/restaurar")
def restaurar(
    id: int, response: Response,
    principal: Principal = Depends(require("prompts:eliminar")),
    cases: PromptUseCases = Depends(prompt_use_cases),
):
    row = _run(lambda: cases.restore(id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(
    id: int, body: PromptEstado, response: Response,
    principal: Principal = Depends(require("prompts:editar")),
    cases: PromptUseCases = Depends(prompt_use_cases),
):
    row = _run(lambda: cases.change_state(id, body.estado_id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row
