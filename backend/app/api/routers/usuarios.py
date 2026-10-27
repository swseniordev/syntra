"""Consultas protegidas del catálogo de Usuarios."""

from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.usuarios import user_commands, user_queries
from app.api.dependencies.auditoria import audit_use_cases
from app.core.identity import Principal, require
from app.modules.auditoria.application.service import AuditUseCases, InvalidAuditCursor
from app.modules.usuarios.application.commands import UserCommands, UserProblem, UserProblemKind
from app.modules.usuarios.application.service import UserQueries, UserQueryProblem, version_tag

router = APIRouter(prefix="/api/v1/usuarios", tags=["Usuarios"])
T = TypeVar("T")
STATUS = {UserProblemKind.VALIDATION: 400, UserProblemKind.FORBIDDEN: 403,
          UserProblemKind.NOT_FOUND: 404, UserProblemKind.CONFLICT: 409,
          UserProblemKind.PRECONDITION_REQUIRED: 428, UserProblemKind.PRECONDITION_FAILED: 412}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except UserProblem as exc:
        raise HTTPException(STATUS[exc.kind], exc.detail) from exc


class UsuarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(min_length=1)
    email: str = Field(min_length=3)
    telefono: str | None = None
    rol_id: int = Field(ge=1)
    grupo_ids: list[int] = Field(default_factory=list)
    estado_id: Literal[1] = 1


class UsuarioPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str | None = None
    email: str | None = None
    telefono: str | None = None
    rol_id: int | None = Field(default=None, ge=1)
    grupo_ids: list[int] | None = None
    estado_id: Literal[0, 1] | None = None


class UsuarioEstado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_id: Literal[0, 1]


@router.get("")
def listar(
    q: str = "", estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    orden: str | None = None, rol_id: int | None = Query(None, ge=1),
    cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require("usuarios:ver")),
    queries: UserQueries = Depends(user_queries),
):
    try:
        return queries.list(q, estado, orden, rol_id, cursor, limite)
    except UserQueryProblem as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("", status_code=201)
def crear(body: UsuarioIn, response: Response,
          principal: Principal = Depends(require("usuarios:crear")),
          commands: UserCommands = Depends(user_commands)):
    row = _run(lambda: commands.create(body.model_dump(exclude={"estado_id"}),
                                        principal.user["id"], principal.permissions, principal.role["ver_todas"]))
    response.headers["ETag"] = version_tag(row)
    response.headers["Location"] = f"/api/v1/usuarios/{row['id']}"
    return row


@router.get("/{id}/historial")
def historial(id: int, response: Response, cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
              principal: Principal = Depends(require("auditoria:ver")),
              audit: AuditUseCases = Depends(audit_use_cases)):
    try:
        items, following = audit.history("Usuario", str(id), cursor, limite)
    except InvalidAuditCursor as exc:
        raise HTTPException(400, str(exc)) from exc
    if following:
        response.headers["X-Next-Cursor"] = following
    return items


@router.post("/{id}/restaurar")
def restaurar(id: int, response: Response,
              principal: Principal = Depends(require("usuarios:eliminar")),
              commands: UserCommands = Depends(user_commands)):
    row = _run(lambda: commands.restore(id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/estado")
def cambiar_estado(id: int, body: UsuarioEstado, response: Response,
                   principal: Principal = Depends(require("usuarios:editar")),
                   commands: UserCommands = Depends(user_commands)):
    row = _run(lambda: commands.change_state(id, body.estado_id, principal.user["id"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.post("/{id}/invitar", status_code=202)
def reenviar(id: int, response: Response,
             principal: Principal = Depends(require("usuarios:editar")),
             commands: UserCommands = Depends(user_commands)):
    process_id = _run(lambda: commands.resend(id, principal.user["id"]))
    response.headers["Location"] = f"/api/v1/procesos/{process_id}"
    return {"proceso_id": process_id, "tipo": "correo_acceso", "estado": "en_cola"}


@router.get("/{id}")
def ver(
    id: int, response: Response,
    principal: Principal = Depends(require("usuarios:ver")),
    queries: UserQueries = Depends(user_queries),
):
    row = queries.get(id)
    if row is None:
        raise HTTPException(404, "Usuario no encontrado")
    response.headers["ETag"] = version_tag(row)
    return row


@router.patch("/{id}")
def editar(id: int, body: UsuarioPatch, response: Response,
           if_match: str | None = Header(default=None, alias="If-Match"),
           principal: Principal = Depends(require("usuarios:editar")),
           commands: UserCommands = Depends(user_commands)):
    changes = body.model_dump(exclude_unset=True)
    if any(changes[key] is None for key in ("nombre", "email", "rol_id", "grupo_ids", "estado_id") if key in changes):
        raise HTTPException(400, "Este campo no admite null")
    row = _run(lambda: commands.edit(id, changes, if_match, principal.user["id"],
                                     principal.permissions, principal.role["ver_todas"]))
    response.headers["ETag"] = version_tag(row)
    return row


@router.delete("/{id}", status_code=204)
def eliminar(id: int, principal: Principal = Depends(require("usuarios:eliminar")),
             commands: UserCommands = Depends(user_commands)):
    _run(lambda: commands.delete(id, principal.user["id"]))
    return Response(status_code=204)
