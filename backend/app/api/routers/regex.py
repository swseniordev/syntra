"""Rutas protegidas de Regex; validación RE2 y control de concurrencia."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auditoria import audit_use_cases
from app.api.dependencies.regex import regex_use_cases
from app.core.identity import Principal, require
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor
from app.modules.regex.application.service import RegexProblem, RegexProblemKind, RegexUseCases, version_tag

router = APIRouter(prefix="/api/v1/regex", tags=["Regex"])
T = TypeVar("T")
HTTP_STATUS = {
    RegexProblemKind.VALIDATION: 400,
    RegexProblemKind.NOT_FOUND: 404,
    RegexProblemKind.CONFLICT: 409,
    RegexProblemKind.PRECONDITION_REQUIRED: 428,
    RegexProblemKind.PRECONDITION_FAILED: 412,
}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except RegexProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class RegexIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(min_length=1)
    condicion: str = Field(min_length=1)
    flags: str = "i"
    texto_prueba: str = Field(min_length=1)
    descripcion: str | None = None
    estado_id: Literal[0, 1] = 1


class RegexPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str | None = None
    condicion: str | None = None
    flags: str | None = None
    texto_prueba: str | None = None
    descripcion: str | None = None
    estado_id: Literal[0, 1] | None = None


class RegexEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


class RegexPrueba(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condicion: str
    flags: str = "i"
    texto: str


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("regex:ver")),
    cases: RegexUseCases = Depends(regex_use_cases),
):
    return _run(lambda: cases.list(q, estado, orden, cursor, limite))


@router.post("/probar")
def probar(
    body: RegexPrueba, principal: Principal = Depends(require("regex:ver")),
    cases: RegexUseCases = Depends(regex_use_cases),
):
    return cases.test(body.condicion, body.flags, body.texto)


@router.get("/{id}/historial")
def historial(
    id: int, response: Response, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("auditoria:ver")),
    cases: AuditUseCases = Depends(audit_use_cases),
):
    try:
        items, following = cases.history("Regex", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.post("", status_code=201)
def crear(
    body: RegexIn, response: Response,
    principal: Principal = Depends(require("regex:crear")),
    cases: RegexUseCases = Depends(regex_use_cases),
):
    row = _run(lambda: cases.create(body.model_dump(), principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/regex/{row['id']}"
    return row


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("regex:ver")),
    cases: RegexUseCases = Depends(regex_use_cases),
):
    row = _run(lambda: cases.get(id))
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(
    id: int, body: RegexPatch, response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("regex:editar")),
    cases: RegexUseCases = Depends(regex_use_cases),
):
    changes = body.model_dump(exclude_unset=True)
    if any(changes[field] is None for field in ("nombre", "condicion", "flags", "texto_prueba", "estado_id") if field in changes):
        raise HTTPException(400, "Este campo no admite null")
    row = _run(lambda: cases.edit(id, changes, if_match, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int, principal: Principal = Depends(require("regex:eliminar")),
    cases: RegexUseCases = Depends(regex_use_cases),
):
    _run(lambda: cases.delete(id, principal.user["id"]))
    return Response(status_code=204)


@router.post("/{id}/restaurar")
def restaurar(
    id: int, response: Response,
    principal: Principal = Depends(require("regex:eliminar")),
    cases: RegexUseCases = Depends(regex_use_cases),
):
    row = _run(lambda: cases.restore(id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(
    id: int, body: RegexEstado, response: Response,
    principal: Principal = Depends(require("regex:editar")),
    cases: RegexUseCases = Depends(regex_use_cases),
):
    row = _run(lambda: cases.change_state(id, body.estado_id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row
