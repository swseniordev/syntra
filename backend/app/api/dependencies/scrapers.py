"""Composición de Scrapers (ejecución) en el borde FastAPI."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.scrapers.application.service import ScraperUseCases
from app.modules.scrapers.infrastructure.postgres import PostgresScraperUnitOfWork


def scraper_use_cases(conn: psycopg.Connection = Depends(connection)) -> ScraperUseCases:
    return ScraperUseCases(PostgresScraperUnitOfWork(conn))
