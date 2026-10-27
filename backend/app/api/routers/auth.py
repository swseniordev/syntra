"""Borde HTTP de sesiones locales: origen, límite por IP y cookies."""

from collections import defaultdict, deque
from datetime import datetime, timezone
import ipaddress
from threading import Lock
import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.dependencies.auth import auth_use_cases
from app.core.config import settings
from app.core.identity import Principal, current_user
from app.modules.auth.application.service import AuthProblem, AuthUseCases, IssuedSession

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticación"])
_ip_attempts: dict[str, deque[float]] = defaultdict(deque)
_ip_lock = Lock()


class Login(BaseModel):
    email: str
    password: str
    recordarme: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expira_en: int = 900


def _origin(request: Request) -> None:
    if request.headers.get("origin") != settings.public_origin:
        raise HTTPException(403, "Origen no permitido")


def _limit_ip(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _ip_lock:
        attempts = _ip_attempts[ip]
        while attempts and attempts[0] <= now - 300:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, "Demasiados intentos; prueba después")
        attempts.append(now)


def _client_ip(request: Request) -> str | None:
    if not request.client:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None


def _set_cookie(response: Response, session: IssuedSession) -> None:
    remaining = max(0, int((session.expires - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie("refresh", session.refresh_token, max_age=remaining, path="/api/v1/auth", httponly=True, secure=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"


def _run(operation):
    try:
        return operation()
    except AuthProblem as problem:
        raise HTTPException(problem.status, problem.detail) from None


@router.post("/login", response_model=Token)
def login(body: Login, request: Request, response: Response, use_cases: AuthUseCases = Depends(auth_use_cases)):
    _origin(request)
    _limit_ip(request)
    session = _run(lambda: use_cases.login(body.email, body.password, body.recordarme, _client_ip(request), request.headers.get("user-agent")))
    _set_cookie(response, session)
    return Token(access_token=session.access_token)


@router.post("/refresh", response_model=Token)
def refresh(request: Request, response: Response, refresh: str | None = Cookie(default=None), use_cases: AuthUseCases = Depends(auth_use_cases)):
    _origin(request)
    session = _run(lambda: use_cases.refresh(refresh, _client_ip(request), request.headers.get("user-agent")))
    _set_cookie(response, session)
    return Token(access_token=session.access_token)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, todas: bool = False, principal: Principal = Depends(current_user), use_cases: AuthUseCases = Depends(auth_use_cases)):
    _origin(request)
    use_cases.logout(principal.user["id"], principal.session_id, todas)
    response.delete_cookie("refresh", path="/api/v1/auth", httponly=True, secure=True, samesite="strict")
    return None


@router.get("/yo")
def me(principal: Principal = Depends(current_user), use_cases: AuthUseCases = Depends(auth_use_cases)):
    return use_cases.me(principal.user, principal.role, principal.permissions)
