"""Composición de Prompts en el borde HTTP."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.prompts.application.service import PromptUseCases
from app.modules.prompts.infrastructure.postgres import PostgresPromptUnitOfWork


def prompt_use_cases(conn: psycopg.Connection = Depends(connection)) -> PromptUseCases:
    return PromptUseCases(PostgresPromptUnitOfWork(conn))
