"""Composición de autenticación en el borde FastAPI."""

from fastapi import Depends
import psycopg

from app.core.db import connection
from app.modules.auth.application.service import AuthUseCases
from app.modules.auth.infrastructure.core_crypto import CoreAuthCrypto
from app.modules.auth.infrastructure.postgres import PostgresAuthStore


def auth_use_cases(conn: psycopg.Connection = Depends(connection)) -> AuthUseCases:
    return AuthUseCases(PostgresAuthStore(conn), CoreAuthCrypto())
