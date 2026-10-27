"""Adaptador HTTP de Clientes: valida solicitudes y traduce resultados y errores."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.dependencies.clientes import client_use_cases
from app.api.dependencies.auditoria import audit_use_cases
from app.core.identity import Principal, require
from app.modules.clientes.application.errors import ClientProblem, ProblemKind
from app.modules.clientes.application.service import ClientUseCases
from app.modules.clientes.application.versioning import version_tag
from app.modules.clientes.domain.rules import normalize_contact, normalize_name, normalize_optional
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor

router = APIRouter(prefix="/api/v1/clientes", tags=["Clientes"])
T = TypeVar("T")
HTTP_STATUS = {
    ProblemKind.VALIDATION: 400,
    ProblemKind.NOT_FOUND: 404,
    ProblemKind.CONFLICT: 409,
    ProblemKind.PRECONDITION_REQUIRED: 428,
    ProblemKind.PRECONDITION_FAILED: 412,
}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ClientProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class ClienteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(min_length=1)
    rfc: str | None = None
    sector: str | None = None
    contacto: str | None = None
    estado_id: Literal[0, 1] = 1

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str) -> str:
        return normalize_name(value)

    @field_validator("rfc", "sector", mode="before")
    @classmethod
    def limpiar_opcionales(cls, value: str | None, info):
        is_sector = info.field_name == "sector"
        return normalize_optional(value, collapse_spaces=is_sector, uppercase=is_sector) if isinstance(value, str) or value is None else value

    @field_validator("contacto")
    @classmethod
    def contacto_email(cls, value: str | None) -> str | None:
        return normalize_contact(value)


class ClientePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str | None = None
    rfc: str | None = None
    sector: str | None = None
    contacto: str | None = None

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Nombre obligatorio")
        return normalize_name(value)

    @field_validator("rfc", "sector", mode="before")
    @classmethod
    def limpiar_opcionales(cls, value: str | None, info):
        is_sector = info.field_name == "sector"
        return normalize_optional(value, collapse_spaces=is_sector, uppercase=is_sector) if isinstance(value, str) or value is None else value

    @field_validator("contacto")
    @classmethod
    def contacto_email(cls, value: str | None) -> str | None:
        return normalize_contact(value)


class ClienteEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, sector: str = "", cursor: str | None = None,
    limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("clientes:ver")),
    cases: ClientUseCases = Depends(client_use_cases),
):
    return _run(lambda: cases.list(q, estado, orden, sector, cursor, limite))


@router.get("/sectores")
def listar_sectores(
    principal: Principal = Depends(require("clientes:ver")),
    cases: ClientUseCases = Depends(client_use_cases),
):
    return _run(cases.sectors)


@router.get("/{id}/historial")
def historial(
    id: int, response: Response, cursor: str | None = None,
    limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    try:
        items, following = cases.history("Cliente", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.post("", status_code=201)
def crear(
    body: ClienteIn, response: Response,
    principal: Principal = Depends(require("clientes:crear")),
    cases: ClientUseCases = Depends(client_use_cases),
):
    row = _run(lambda: cases.create(body.model_dump(), principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/clientes/{row['id']}"
    return row


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("clientes:ver")),
    cases: ClientUseCases = Depends(client_use_cases),
):
    row = _run(lambda: cases.get(id))
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(
    id: int, body: ClientePatch, response: Response, if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("clientes:editar")),
    cases: ClientUseCases = Depends(client_use_cases),
):
    row = _run(lambda: cases.edit(id, body.model_dump(exclude_unset=True), if_match, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int,
    principal: Principal = Depends(require("clientes:eliminar")),
    cases: ClientUseCases = Depends(client_use_cases),
):
    _run(lambda: cases.delete(id, principal.user["id"]))
    return Response(status_code=204)


@router.post("/{id}/restaurar")
def restaurar(
    id: int, response: Response,
    principal: Principal = Depends(require("clientes:eliminar")),
    cases: ClientUseCases = Depends(client_use_cases),
):
    row = _run(lambda: cases.restore(id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(
    id: int, body: ClienteEstado, response: Response,
    principal: Principal = Depends(require("clientes:editar")),
    cases: ClientUseCases = Depends(client_use_cases),
):
    row = _run(lambda: cases.change_state(id, body.estado_id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row
