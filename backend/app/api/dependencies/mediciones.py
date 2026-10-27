"""Composición PostgreSQL del módulo de Mediciones."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.mediciones.application.service import MeasurementUseCases
from app.modules.mediciones.infrastructure.postgres import PostgresMeasurementUnitOfWork


def measurement_use_cases(conn: psycopg.Connection = Depends(connection)) -> MeasurementUseCases:
    return MeasurementUseCases(PostgresMeasurementUnitOfWork(conn))
