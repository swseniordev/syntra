"""Composición de consultas de Auditoría en el borde HTTP."""

import psycopg
from fastapi import Depends

from app.core.db import connection
from app.modules.auditoria.application.service import AuditUseCases
from app.modules.auditoria.infrastructure.postgres import PostgresAuditReader
from app.modules.auditoria.application.export import AuditExports
from app.modules.auditoria.infrastructure.export_postgres import PostgresExportStore


def audit_use_cases(conn: psycopg.Connection = Depends(connection)) -> AuditUseCases:
    return AuditUseCases(PostgresAuditReader(conn))


def audit_exports(conn: psycopg.Connection = Depends(connection)) -> AuditExports:
    return AuditExports(PostgresExportStore(conn))
