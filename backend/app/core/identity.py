"""Identidad y permisos vigentes desde PostgreSQL en cada solicitud protegida."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
import psycopg

from app.core.db import connection
from app.core.security import verify_access

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user: dict
    role: dict
    permissions: frozenset[str]
    session_id: uuid.UUID


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    conn: psycopg.Connection = Depends(connection),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Se requiere Bearer JWT")
    try:
        claims = verify_access(credentials.credentials)
        sid = uuid.UUID(claims["jti"].split(":", 1)[0])
        uid = int(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(401, "Token inválido") from None
    row = conn.execute(
        """SELECT u.id,u.nombre,u.email,u.telefono,u.rol_id,u.estado_id,u.version_token,
                  u.ultimo_acceso,u.creado_en,u.creado_por,u.actualizado_en,u.actualizado_por,
                  r.nombre AS rol_nombre,r.descripcion AS rol_descripcion,r.ver_todas,r.estado_id AS rol_estado,
                  s.id AS sesion_id,s.revocado_en,s.expira_en
             FROM seg.usuario u JOIN seg.rol r ON r.id=u.rol_id
             JOIN seg.sesion s ON s.usuario_id=u.id
            WHERE u.id=%s AND s.id=%s""",
        (uid, sid),
    ).fetchone()
    if not row or row["estado_id"] != 1 or row["rol_estado"] != 1 or row["revocado_en"] is not None or row["expira_en"] <= datetime.now(timezone.utc):
        raise HTTPException(401, "Sesión no válida")
    if row["version_token"] != claims["ver"] or row["rol_id"] != claims["rol"]:
        raise HTTPException(401, "Sesión invalidada")
    permissions = frozenset(
        f"{p['modulo']}:{p['accion']}"
        for p in conn.execute("SELECT modulo,accion FROM seg.rol_permiso WHERE rol_id=%s", (row["rol_id"],))
    )
    digest = hashlib.sha256("\n".join(sorted(permissions)).encode()).hexdigest()
    if digest != claims["permisos"] or row["ver_todas"] != claims.get("ver_todas"):
        raise HTTPException(401, "Permisos cambiaron; renueva la sesión")
    return Principal(row, {"id": row["rol_id"], "nombre": row["rol_nombre"], "descripcion": row["rol_descripcion"], "ver_todas": row["ver_todas"], "estado_id": row["rol_estado"]}, permissions, sid)


def require(permission: str):
    def check(principal: Principal = Depends(current_user)) -> Principal:
        if permission not in principal.permissions:
            raise HTTPException(403, "Permiso insuficiente")
        return principal
    return check
