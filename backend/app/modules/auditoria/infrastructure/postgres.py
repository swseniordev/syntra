"""Escritura de eventos en la transacción recibida, sin commit propio."""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

_SECRET_FRAGMENTS = ("password", "contrasena", "contraseña", "token", "secret", "clave", "credential", "authorization", "api_key")
_DETAIL_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _safe_json(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: clean(val) for key, val in item.items()
                    if not any(fragment in key.lower() for fragment in _SECRET_FRAGMENTS)}
        if isinstance(item, (list, tuple)):
            return [clean(val) for val in item]
        if isinstance(item, (date, datetime, UUID)):
            return str(item)
        return item

    return clean(value)


class PostgresAuditReader:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def summary(self, start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]:
        daily = self.conn.execute(
            "SELECT timezone('America/Bogota',fecha)::date AS dia,count(*) AS total "
            "FROM aud.auditoria WHERE fecha >= %s AND fecha < %s GROUP BY 1 ORDER BY 1",
            (start, end),
        ).fetchall()
        modules = self.conn.execute(
            "SELECT modulo,count(*) AS total FROM aud.auditoria "
            "WHERE fecha >= %s AND fecha < %s GROUP BY modulo ORDER BY total DESC,modulo",
            (start, end),
        ).fetchall()
        return {"por_dia": daily, "por_modulo": modules}

    def list(self, filters: dict[str, Any], before: tuple[datetime, int] | None,
             limit: int) -> list[dict[str, Any]]:
        where = []
        args: list[object] = []
        for key in ("modulo", "usuario_id", "accion", "entidad_tipo", "entidad_id"):
            if filters.get(key) is not None:
                where.append(f"{key}=%s")
                args.append(filters[key])
        if filters.get("desde") is not None:
            where.append("fecha>=%s")
            args.append(filters["desde"])
        if filters.get("hasta") is not None:
            where.append("fecha<=%s")
            args.append(filters["hasta"])
        if filters.get("q"):
            where.append("(entidad_nombre ILIKE %s OR entidad_id ILIKE %s OR detalle ILIKE %s)")
            pattern = f"%{filters['q']}%"
            args.extend((pattern, pattern, pattern))
        if before is not None:
            where.append("(fecha,id)<(%s,%s)")
            args.extend(before)
        args.append(limit)
        condition = " AND ".join(where) if where else "TRUE"
        return self.conn.execute(
            "SELECT id,fecha,usuario_id,modulo,accion,entidad_tipo,entidad_id,entidad_nombre,"
            "antes,despues,detalle,ip,request_id FROM aud.auditoria WHERE " + condition +
            " ORDER BY fecha DESC,id DESC LIMIT %s", args,
        ).fetchall()

    def get(self, row_id: int, date: datetime) -> dict[str, Any] | None:
        return self.conn.execute(
            "SELECT id,fecha,usuario_id,modulo,accion,entidad_tipo,entidad_id,entidad_nombre,"
            "antes,despues,detalle,ip,request_id FROM aud.auditoria WHERE fecha=%s AND id=%s",
            (date, row_id),
        ).fetchone()

    def history(
        self, entity_type: str, entity_id: str, before: tuple[datetime, int] | None, limit: int,
    ) -> list[dict[str, Any]]:
        where = "entidad_tipo=%s AND entidad_id=%s"
        args: list[object] = [entity_type, entity_id]
        if before is not None:
            where += " AND (fecha,id)<(%s,%s)"
            args.extend(before)
        args.append(limit)
        return self.conn.execute(
            "SELECT id,fecha,usuario_id,modulo,accion,entidad_tipo,entidad_id,entidad_nombre,"
            "antes,despues,detalle,ip,request_id FROM aud.auditoria WHERE " + where +
            " ORDER BY fecha DESC,id DESC LIMIT %s", args,
        ).fetchall()


class PostgresAuditWriter:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def record(
        self,
        *,
        actor_id: int | None,
        module: str,
        action: str,
        entity_type: str,
        entity_id: str | None,
        entity_name: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        detail: str | None = None,
    ) -> None:
        if detail is not None and not _DETAIL_CODE.fullmatch(detail):
            raise ValueError("El detalle de auditoría debe ser un código fijo sin datos externos")
        self.conn.execute(
            """INSERT INTO aud.auditoria
                   (usuario_id,modulo,accion,entidad_tipo,entidad_id,entidad_nombre,antes,despues,detalle)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                actor_id, module, action, entity_type, entity_id, entity_name,
                Jsonb(_safe_json(before)) if before is not None else None,
                Jsonb(_safe_json(after)) if after is not None else None,
                detail,
            ),
        )
