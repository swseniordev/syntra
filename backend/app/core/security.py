"""Firma RS256 y credenciales opacas de sesión."""

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import secrets
import uuid

import jwt
from argon2 import PasswordHasher
from cryptography.hazmat.primitives import serialization

from app.core.config import settings

password_hasher = PasswordHasher()


def _keys():
    private = serialization.load_pem_private_key(Path(settings.jwt_private_key).read_bytes(), password=None)
    public = private.public_key()
    public_pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    kid = hashlib.sha256(public_pem).hexdigest()[:16]
    return private, public, kid


def sign_access(user: dict, session_id: uuid.UUID, permissions: list[str], ver_todas: bool) -> str:
    private, _, kid = _keys()
    now = datetime.now(timezone.utc)
    permission_hash = hashlib.sha256("\n".join(sorted(permissions)).encode()).hexdigest()
    return jwt.encode(
        {
            "sub": str(user["id"]), "rol": user["rol_id"], "permisos": permission_hash,
            "ver_todas": ver_todas, "ver": user["version_token"],
            "jti": f"{session_id}:{uuid.uuid4()}", "iat": now, "exp": now + timedelta(minutes=15),
        },
        private, algorithm="RS256", headers={"kid": kid},
    )


def verify_access(token: str) -> dict:
    _, public, kid = _keys()
    header = jwt.get_unverified_header(token)
    if header.get("kid") != kid or header.get("alg") != "RS256":
        raise jwt.InvalidTokenError("Clave no reconocida")
    return jwt.decode(token, public, algorithms=["RS256"], options={"require": ["sub", "rol", "permisos", "ver", "jti", "iat", "exp"]})


def sign_audit_download(user_id: int, session_id: uuid.UUID, process_id: int) -> str:
    private, _, kid = _keys()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "sid": str(session_id), "pid": process_id,
         "aud": "syntra-auditoria-descarga", "iat": now, "exp": now + timedelta(minutes=15)},
        private, algorithm="RS256", headers={"kid": kid},
    )


def verify_audit_download(token: str, user_id: int, session_id: uuid.UUID, process_id: int) -> bool:
    try:
        _, public, kid = _keys()
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or header.get("kid") != kid:
            return False
        claims = jwt.decode(token, public, algorithms=["RS256"], audience="syntra-auditoria-descarga",
                            options={"require": ["sub", "sid", "pid", "aud", "iat", "exp"]})
        return claims["sub"] == str(user_id) and claims["sid"] == str(session_id) and claims["pid"] == process_id
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return False


def sign_measurement_file_download(user_id: int, session_id: uuid.UUID, file_id: int) -> str:
    private, _, kid = _keys()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "sid": str(session_id), "fid": file_id,
         "aud": "syntra-medicion-archivo", "iat": now, "exp": now + timedelta(minutes=15)},
        private, algorithm="RS256", headers={"kid": kid},
    )


def verify_measurement_file_download(token: str, user_id: int, session_id: uuid.UUID,
                                     file_id: int) -> bool:
    try:
        _, public, kid = _keys()
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or header.get("kid") != kid:
            return False
        claims = jwt.decode(token, public, algorithms=["RS256"],
                            audience="syntra-medicion-archivo",
                            options={"require": ["sub", "sid", "fid", "aud", "iat", "exp"]})
        return claims["sub"] == str(user_id) and claims["sid"] == str(session_id) and claims["fid"] == file_id
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return False


def sign_format_template_download(user_id: int, session_id: uuid.UUID, format_id: str,
                                 columns_digest: str) -> str:
    private, _, kid = _keys()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "sid": str(session_id), "fid": format_id, "cols": columns_digest,
         "aud": "syntra-formato-plantilla", "iat": now, "exp": now + timedelta(minutes=15)},
        private, algorithm="RS256", headers={"kid": kid},
    )


def verify_format_template_download(token: str, user_id: int, session_id: uuid.UUID,
                                    format_id: str, columns_digest: str) -> bool:
    try:
        _, public, kid = _keys()
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or header.get("kid") != kid:
            return False
        claims = jwt.decode(token, public, algorithms=["RS256"], audience="syntra-formato-plantilla",
                            options={"require": ["sub", "sid", "fid", "cols", "aud", "iat", "exp"]})
        return (claims["sub"] == str(user_id) and claims["sid"] == str(session_id)
                and claims["fid"] == format_id and claims["cols"] == columns_digest)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return False


def new_refresh(session_id: uuid.UUID, version: int) -> tuple[str, bytes]:
    token = f"{session_id}.{version}.{secrets.token_urlsafe(48)}"
    return token, hashlib.sha256(token.encode()).digest()


def refresh_identity(token: str) -> tuple[uuid.UUID, int]:
    prefix, version, secret = token.split(".", 2)
    if not secret or int(version) < 1:
        raise ValueError("Refresh inválido")
    return uuid.UUID(prefix), int(version)
