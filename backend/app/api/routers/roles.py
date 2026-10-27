"""Transporte HTTP de Roles, con permisos de entrada y errores del contrato."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.roles import role_use_cases
from app.api.dependencies.auditoria import audit_use_cases
from app.core.identity import Principal, require
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor
from app.modules.roles.application.service import RoleProblem, RoleProblemKind, RoleUseCases, version_tag

router = APIRouter(prefix="/api/v1/roles", tags=["Roles"])
T = TypeVar("T")
HTTP_STATUS = {
    RoleProblemKind.VALIDATION: 400,
    RoleProblemKind.FORBIDDEN: 403,
    RoleProblemKind.NOT_FOUND: 404,
    RoleProblemKind.CONFLICT: 409,
    RoleProblemKind.PRECONDITION_REQUIRED: 428,
    RoleProblemKind.PRECONDITION_FAILED: 412,
}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except RoleProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class RolIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(min_length=1)
    descripcion: str | None = None
    ver_todas: bool = False
    permisos: dict[str, list[str]]
    estado_id: Literal[0, 1] = 1


class RolPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str | None = None
    descripcion: str | None = None
    ver_todas: bool | None = None
    permisos: dict[str, list[str]] | None = None
    estado_id: Literal[0, 1] | None = None


class RolEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("roles:ver")),
    cases: RoleUseCases = Depends(role_use_cases),
):
    return _run(lambda: cases.list(q, estado, orden, cursor, limite))


@router.get("/catalogo-permisos")
def catalogo(
    principal: Principal = Depends(require("roles:ver")),
    cases: RoleUseCases = Depends(role_use_cases),
):
    return _run(cases.catalog)


@router.get("/{id}/historial")
def historial(
    id: int, response: Response, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    try:
        items, following = cases.history("Rol", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.post("", status_code=201)
def crear(
    body: RolIn, response: Response,
    principal: Principal = Depends(require("roles:crear")),
    cases: RoleUseCases = Depends(role_use_cases),
):
    row = _run(lambda: cases.create(body.model_dump(), principal.user["id"], principal.permissions, principal.role["ver_todas"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/roles/{row['id']}"
    return row


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("roles:ver")),
    cases: RoleUseCases = Depends(role_use_cases),
):
    row = _run(lambda: cases.get(id))
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(
    id: int, body: RolPatch, response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("roles:editar")),
    cases: RoleUseCases = Depends(role_use_cases),
):
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(field) is None for field in ("nombre", "ver_todas", "permisos", "estado_id") if field in changes):
        raise HTTPException(400, "Este campo no admite null")
    row = _run(lambda: cases.edit(id, changes, if_match, principal.user["id"], principal.permissions, principal.role["ver_todas"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int, principal: Principal = Depends(require("roles:eliminar")),
    cases: RoleUseCases = Depends(role_use_cases),
):
    _run(lambda: cases.delete(id, principal.user["id"]))
    return Response(status_code=204)


@router.post("/{id}/restaurar")
def restaurar(
    id: int, response: Response,
    principal: Principal = Depends(require("roles:eliminar")),
    cases: RoleUseCases = Depends(role_use_cases),
):
    row = _run(lambda: cases.restore(id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(
    id: int, body: RolEstado, response: Response,
    principal: Principal = Depends(require("roles:editar")),
    cases: RoleUseCases = Depends(role_use_cases),
):
    row = _run(lambda: cases.change_state(id, body.estado_id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row
