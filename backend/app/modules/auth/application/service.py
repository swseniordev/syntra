"""Casos de uso de autenticación y sesiones; sin HTTP ni SQL."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import logging
import uuid

from app.modules.auth.application.ports import AuthCrypto, AuthRow, AuthStore
from app.modules.auth.domain.rules import failed_login, family_expiry

log = logging.getLogger(__name__)


class AuthProblem(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    expires: datetime


class AuthUseCases:
    def __init__(self, store: AuthStore, crypto: AuthCrypto):
        self.store = store
        self.crypto = crypto

    def login(self, email: str, password: str, remember: bool, ip: str | None, user_agent: str | None) -> IssuedSession:
        user = self.store.lock_login_user(email.strip())
        valid_password = self.crypto.verify_password(user["password_hash"] if user else None, password)
        now = datetime.now(timezone.utc)
        if not user or user["estado_id"] != 1 or user["rol_estado"] != 1:
            log.warning("Login denegado para identidad desconocida o inactiva desde %s", ip or "unknown")
            raise AuthProblem(401, "Credenciales inválidas")
        if user["bloqueado_hasta"] and user["bloqueado_hasta"] > now:
            raise AuthProblem(429, "Cuenta bloqueada temporalmente")
        if not valid_password:
            failures, until = failed_login(user["intentos_fallidos"], now)
            self.store.failed_login(user["id"], failures, until)
            self.store.commit()
            log.warning("Login fallido usuario=%s desde %s", user["id"], ip or "unknown")
            raise AuthProblem(401, "Credenciales inválidas")
        self.store.successful_login(user["id"], now)
        session_id, family_id = uuid.uuid4(), uuid.uuid4()
        token, token_hash = self.crypto.new_refresh(session_id, user["version_token"])
        expires = family_expiry(now, remember)
        self.store.create_session(session_id, family_id, user["id"], token_hash, expires, ip, user_agent)
        access = self.crypto.sign_access(user, session_id, self.store.permissions(user["rol_id"]), user["ver_todas"])
        self.store.commit()
        return IssuedSession(access, token, expires)

    def refresh(self, token: str | None, ip: str | None, user_agent: str | None) -> IssuedSession:
        if not token:
            raise AuthProblem(401, "Falta refresh")
        try:
            session_id, issued_version = self.crypto.refresh_identity(token)
        except (ValueError, AttributeError):
            raise AuthProblem(401, "Refresh inválido") from None
        session = self.store.lock_session(session_id)
        if not session or not hmac.compare_digest(bytes(session["refresh_hash"]), hashlib.sha256(token.encode()).digest()):
            raise AuthProblem(401, "Refresh inválido")
        if session["revocado_en"] is not None:
            if self.store.has_active_successor(session["familia_id"]):
                self.store.revoke_family(session["familia_id"])
                self.store.commit()
                log.warning("Reutilización de refresh en familia=%s", session["familia_id"])
            raise AuthProblem(401, "Refresh revocado")
        if session["expira_en"] <= datetime.now(timezone.utc):
            raise AuthProblem(401, "Refresh vencido")
        user = self.store.refresh_user(session["usuario_id"])
        if not user or user["estado_id"] != 1 or user["rol_estado"] != 1:
            raise AuthProblem(401, "Usuario inactivo")
        if user["version_token"] != issued_version:
            raise AuthProblem(401, "Sesión invalidada")
        next_id = uuid.uuid4()
        next_token, next_hash = self.crypto.new_refresh(next_id, issued_version)
        self.store.revoke_session(session_id)
        self.store.create_session(next_id, session["familia_id"], user["id"], next_hash, session["expira_en"], ip, user_agent)
        access = self.crypto.sign_access(user, next_id, self.store.permissions(user["rol_id"]), user["ver_todas"])
        self.store.commit()
        return IssuedSession(access, next_token, session["expira_en"])

    def logout(self, user_id: int, session_id: uuid.UUID, all_sessions: bool) -> None:
        if all_sessions:
            self.store.revoke_user_sessions(user_id)
            self.store.increment_user_version(user_id)
        else:
            self.store.revoke_session(session_id)
        self.store.commit()

    def me(self, user: AuthRow, role: AuthRow, effective_permissions: frozenset[str]) -> dict:
        visible = self.store.visible_account_ids(user["id"])
        permissions: dict[str, list[str]] = {}
        for pair in sorted(effective_permissions):
            module, action = pair.split(":", 1)
            permissions.setdefault(module, []).append(action)
        return {
            "usuario": {key: user[key] for key in ("id", "nombre", "email", "telefono", "rol_id", "estado_id", "ultimo_acceso", "creado_en", "creado_por", "actualizado_en", "actualizado_por")},
            "rol": role, "permisos": permissions, "cuentas_visibles": visible, "tarjetas": {},
        }
