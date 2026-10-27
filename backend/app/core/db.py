"""Conexiones PostgreSQL con libpq/pgpass; jamás conectar la API como postgres."""

from collections.abc import Iterator

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings


def connection() -> Iterator[psycopg.Connection]:
    if settings.database_user in {"postgres", "svc_api"}:
        raise RuntimeError("La API requiere syntra_api_login")
    with psycopg.connect(
        host=settings.database_host,
        port=settings.database_port,
        dbname=settings.database_name,
        user=settings.database_user,
        passfile=str(settings.database_passfile),
        row_factory=dict_row,
        connect_timeout=5,
        application_name="syntra_api",
    ) as conn:
        yield conn
