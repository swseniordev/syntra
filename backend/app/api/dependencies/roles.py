"""Composición de Roles en el borde FastAPI."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.roles.application.service import RoleUseCases
from app.modules.roles.infrastructure.postgres import PostgresRoleUnitOfWork


def role_use_cases(conn: psycopg.Connection = Depends(connection)) -> RoleUseCases:
    return RoleUseCases(PostgresRoleUnitOfWork(conn))
