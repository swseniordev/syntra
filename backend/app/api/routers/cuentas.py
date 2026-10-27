"""Contrato HTTP de Cuentas con visibilidad, permisos y ETag."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auditoria import audit_use_cases
from app.api.dependencies.cuentas import account_use_cases
from app.core.identity import Principal, require
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor
from app.modules.cuentas.application.service import AccountProblem, AccountProblemKind, AccountUseCases, version_tag

router = APIRouter(prefix="/api/v1/cuentas", tags=["Cuentas"])
T = TypeVar("T")
Taxonomy = Literal["gobierno", "comparativo", "electoral"]
HTTP_STATUS = {
    AccountProblemKind.VALIDATION: 400,
    AccountProblemKind.NOT_FOUND: 404,
    AccountProblemKind.CONFLICT: 409,
    AccountProblemKind.PRECONDITION_REQUIRED: 428,
    AccountProblemKind.PRECONDITION_FAILED: 412,
}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except AccountProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class CuentaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cliente_id: int = Field(ge=1)
    nombre: str = Field(min_length=1)
    actor_principal: str | None = None
    entidad: str | None = None
    taxonomia: Taxonomy | None = None
    prompt_clusters: str = Field(min_length=1)
    prompt_temas: str = Field(min_length=1)
    estado_id: Literal[0, 1] = 1


class CuentaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cliente_id: int | None = Field(default=None, ge=1)
    nombre: str | None = None
    actor_principal: str | None = None
    entidad: str | None = None
    taxonomia: Taxonomy | None = None
    prompt_clusters: str | None = None
    prompt_temas: str | None = None
    estado_id: Literal[0, 1] | None = None


class CuentaEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


def _global(principal: Principal) -> bool:
    return bool(principal.role["ver_todas"])


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, cliente_id: int | None = Query(None, ge=1),
    cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("cuentas:ver")),
    cases: AccountUseCases = Depends(account_use_cases),
):
    return _run(lambda: cases.list(q, estado, orden, cliente_id, cursor, limite,
                                   principal.user["id"], _global(principal)))


@router.get("/{id}/historial")
def historial(
    id: int, response: Response, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AccountUseCases = Depends(account_use_cases),
    audit: AuditUseCases = Depends(audit_use_cases),
):
    _run(lambda: cases.get(id, principal.user["id"], _global(principal)))
    try:
        items, following = audit.history("Cuenta", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.post("", status_code=201)
def crear(
    body: CuentaIn, response: Response,
    principal: Principal = Depends(require("cuentas:crear")),
    cases: AccountUseCases = Depends(account_use_cases),
):
    row = _run(lambda: cases.create(body.model_dump(), principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/cuentas/{row['id']}"
    return row


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("cuentas:ver")),
    cases: AccountUseCases = Depends(account_use_cases),
):
    row = _run(lambda: cases.get(id, principal.user["id"], _global(principal)))
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(
    id: int, body: CuentaPatch, response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("cuentas:editar")),
    cases: AccountUseCases = Depends(account_use_cases),
):
    changes = body.model_dump(exclude_unset=True)
    if any(changes[field] is None for field in ("cliente_id", "nombre", "prompt_clusters", "prompt_temas", "estado_id") if field in changes):
        raise HTTPException(400, "Este campo no admite null")
    row = _run(lambda: cases.edit(id, changes, if_match, principal.user["id"], _global(principal)))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int, principal: Principal = Depends(require("cuentas:eliminar")),
    cases: AccountUseCases = Depends(account_use_cases),
):
    _run(lambda: cases.delete(id, principal.user["id"], _global(principal)))
    return Response(status_code=204)


@router.post("/{id}/restaurar")
def restaurar(
    id: int, response: Response,
    principal: Principal = Depends(require("cuentas:eliminar")),
    cases: AccountUseCases = Depends(account_use_cases),
):
    row = _run(lambda: cases.restore(id, principal.user["id"], _global(principal)))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(
    id: int, body: CuentaEstado, response: Response,
    principal: Principal = Depends(require("cuentas:editar")),
    cases: AccountUseCases = Depends(account_use_cases),
):
    row = _run(lambda: cases.change_state(id, body.estado_id, principal.user["id"], _global(principal)))
    response.headers["ETag"] = version_tag(row)
    return row
