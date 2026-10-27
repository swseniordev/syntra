"""Composición de Regex en el borde HTTP."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.regex.application.service import RegexUseCases
from app.modules.regex.infrastructure.postgres import PostgresRegexUnitOfWork
from app.modules.regex.infrastructure.re2_engine import RE2Evaluator


def regex_use_cases(conn: psycopg.Connection = Depends(connection)) -> RegexUseCases:
    return RegexUseCases(PostgresRegexUnitOfWork(conn), RE2Evaluator())
