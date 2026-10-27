"""Composición de consultas de Usuarios."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.usuarios.application.service import UserQueries
from app.modules.usuarios.application.commands import UserCommands
from app.modules.usuarios.infrastructure.postgres import PostgresUserReader
from app.modules.usuarios.infrastructure.commands_postgres import PostgresUserUnitOfWork


def user_queries(conn: psycopg.Connection = Depends(connection)) -> UserQueries:
    return UserQueries(PostgresUserReader(conn))


def user_commands(conn: psycopg.Connection = Depends(connection)) -> UserCommands:
    return UserCommands(PostgresUserUnitOfWork(conn))
