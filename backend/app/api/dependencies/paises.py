"""Composición de Países en el borde FastAPI."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.paises.application.service import CountryUseCases
from app.modules.paises.infrastructure.postgres import PostgresCountryUnitOfWork


def country_use_cases(conn: psycopg.Connection = Depends(connection)) -> CountryUseCases:
    return CountryUseCases(PostgresCountryUnitOfWork(conn))
