"""Composición de Cuentas en el borde FastAPI."""

import psycopg
from fastapi import Depends

from app.core.config import settings
from app.core.db import connection
from app.modules.cuentas.application.service import AccountUseCases
from app.modules.cuentas.infrastructure.postgres import PostgresAccountUnitOfWork


def account_use_cases(conn: psycopg.Connection = Depends(connection)) -> AccountUseCases:
    return AccountUseCases(PostgresAccountUnitOfWork(conn),
                           attempts=settings.account_provision_attempts,
                           backoff_ms=settings.account_provision_backoff_ms)
