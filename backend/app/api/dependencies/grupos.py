"""Composición HTTP del módulo Grupos."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.grupos.application.service import GroupUseCases
from app.modules.grupos.infrastructure.postgres import PostgresGroupUnitOfWork


def group_use_cases(conn: psycopg.Connection = Depends(connection)) -> GroupUseCases:
    return GroupUseCases(PostgresGroupUnitOfWork(conn))
