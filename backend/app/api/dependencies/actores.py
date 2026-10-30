"""Composición de Actores en el borde FastAPI."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.actores.application.service import ActorUseCases
from app.modules.actores.infrastructure.postgres import PostgresActorUnitOfWork


def actor_use_cases(conn: psycopg.Connection = Depends(connection)) -> ActorUseCases:
    return ActorUseCases(PostgresActorUnitOfWork(conn))
