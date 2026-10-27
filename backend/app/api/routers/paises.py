"""HTTP de Países: permisos, contrato, ETag y errores."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auditoria import audit_use_cases
from app.api.dependencies.paises import country_use_cases
from app.core.identity import Principal, require
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor
from app.modules.paises.application.service import CountryProblem, CountryProblemKind, CountryUseCases, version_tag

router = APIRouter(prefix="/api/v1/paises", tags=["Países"])
T = TypeVar("T")
HTTP_STATUS = {
    CountryProblemKind.VALIDATION: 400,
    CountryProblemKind.NOT_FOUND: 404,
    CountryProblemKind.CONFLICT: 409,
    CountryProblemKind.PRECONDITION_REQUIRED: 428,
    CountryProblemKind.PRECONDITION_FAILED: 412,
}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except CountryProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class PaisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(min_length=1)
    codigo: str = Field(pattern=r"^[A-Z]{2}$")
    idioma: str = "es-419"
    estado_id: Literal[0, 1] = 1


class PaisPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str | None = None
    codigo: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    idioma: str | None = None
    estado_id: Literal[0, 1] | None = None


class PaisEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("paises:ver")),
    cases: CountryUseCases = Depends(country_use_cases),
):
    return _run(lambda: cases.list(q, estado, orden, cursor, limite))


@router.get("/{id}/historial")
def historial(
    id: int, response: Response, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    try:
        items, following = cases.history("País", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.post("", status_code=201)
def crear(
    body: PaisIn, response: Response,
    principal: Principal = Depends(require("paises:crear")),
    cases: CountryUseCases = Depends(country_use_cases),
):
    row = _run(lambda: cases.create(body.model_dump(), principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/paises/{row['id']}"
    return row


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("paises:ver")),
    cases: CountryUseCases = Depends(country_use_cases),
):
    row = _run(lambda: cases.get(id))
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(
    id: int, body: PaisPatch, response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("paises:editar")),
    cases: CountryUseCases = Depends(country_use_cases),
):
    changes = body.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(400, "Este campo no admite null")
    row = _run(lambda: cases.edit(id, changes, if_match, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int, principal: Principal = Depends(require("paises:eliminar")),
    cases: CountryUseCases = Depends(country_use_cases),
):
    _run(lambda: cases.delete(id, principal.user["id"]))
    return Response(status_code=204)


@router.post("/{id}/restaurar")
def restaurar(
    id: int, response: Response,
    principal: Principal = Depends(require("paises:eliminar")),
    cases: CountryUseCases = Depends(country_use_cases),
):
    row = _run(lambda: cases.restore(id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(
    id: int, body: PaisEstado, response: Response,
    principal: Principal = Depends(require("paises:editar")),
    cases: CountryUseCases = Depends(country_use_cases),
):
    row = _run(lambda: cases.change_state(id, body.estado_id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row
