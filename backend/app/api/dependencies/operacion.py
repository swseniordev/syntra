"""Composición del caso de uso de monitorización."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.operacion.application.monitor import OperationsMonitor
from app.modules.operacion.infrastructure.postgres import PostgresOperationsReader


def operations_monitor(conn: psycopg.Connection = Depends(connection)) -> OperationsMonitor:
    return OperationsMonitor(PostgresOperationsReader(conn))
