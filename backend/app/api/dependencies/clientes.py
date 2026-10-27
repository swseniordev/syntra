"""Composición de Clientes en el borde FastAPI."""

from fastapi import Depends
import psycopg

from app.core.db import connection
from app.modules.clientes.application.service import ClientUseCases
from app.modules.clientes.infrastructure.postgres import PostgresClientUnitOfWork


def client_use_cases(conn: psycopg.Connection = Depends(connection)) -> ClientUseCases:
    return ClientUseCases(PostgresClientUnitOfWork(conn))
