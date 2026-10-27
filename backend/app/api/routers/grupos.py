"""Contrato HTTP de Grupos: permisos, ETag y vínculos reales."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auditoria import audit_use_cases
from app.api.dependencies.grupos import group_use_cases
from app.core.identity import Principal, require
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor
from app.modules.grupos.application.service import GroupProblem, GroupProblemKind, GroupUseCases, version_tag

router = APIRouter(prefix="/api/v1/grupos", tags=["Grupos"])
T = TypeVar("T")
HTTP_STATUS = {
    GroupProblemKind.VALIDATION: 400,
    GroupProblemKind.NOT_FOUND: 404,
    GroupProblemKind.CONFLICT: 409,
    GroupProblemKind.PRECONDITION_REQUIRED: 428,
    GroupProblemKind.PRECONDITION_FAILED: 412,
}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except GroupProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class GrupoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(min_length=1)
    descripcion: str | None = None
    usuario_ids: list[int] = Field(default_factory=list)
    cuenta_ids: list[int] = Field(default_factory=list)
    estado_id: Literal[0, 1] = 1


class GrupoPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str | None = None
    descripcion: str | None = None
    usuario_ids: list[int] | None = None
    cuenta_ids: list[int] | None = None
    estado_id: Literal[0, 1] | None = None


class GrupoEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("grupos:ver")),
    cases: GroupUseCases = Depends(group_use_cases),
):
    return _run(lambda: cases.list(q, estado, orden, cursor, limite))


@router.get("/{id}/historial")
def historial(
    id: int, response: Response, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    groups: GroupUseCases = Depends(group_use_cases),
    audit: AuditUseCases = Depends(audit_use_cases),
):
    _run(lambda: groups.get(id))
    try:
        items, following = audit.history("Grupo", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.post("", status_code=201)
def crear(
    body: GrupoIn, response: Response,
    principal: Principal = Depends(require("grupos:crear")),
    cases: GroupUseCases = Depends(group_use_cases),
):
    row = _run(lambda: cases.create(body.model_dump(), principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/grupos/{row['id']}"
    return row


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("grupos:ver")),
    cases: GroupUseCases = Depends(group_use_cases),
):
    row = _run(lambda: cases.get(id))
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(
    id: int, body: GrupoPatch, response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("grupos:editar")),
    cases: GroupUseCases = Depends(group_use_cases),
):
    changes = body.model_dump(exclude_unset=True)
    if any(changes[field] is None for field in ("nombre", "usuario_ids", "cuenta_ids", "estado_id") if field in changes):
        raise HTTPException(400, "Este campo no admite null")
    row = _run(lambda: cases.edit(id, changes, if_match, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int, principal: Principal = Depends(require("grupos:eliminar")),
    cases: GroupUseCases = Depends(group_use_cases),
):
    _run(lambda: cases.delete(id, principal.user["id"]))
    return Response(status_code=204)


@router.post("/{id}/restaurar")
def restaurar(
    id: int, response: Response,
    principal: Principal = Depends(require("grupos:eliminar")),
    cases: GroupUseCases = Depends(group_use_cases),
):
    row = _run(lambda: cases.restore(id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(
    id: int, body: GrupoEstado, response: Response,
    principal: Principal = Depends(require("grupos:editar")),
    cases: GroupUseCases = Depends(group_use_cases),
):
    row = _run(lambda: cases.change_state(id, body.estado_id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row
