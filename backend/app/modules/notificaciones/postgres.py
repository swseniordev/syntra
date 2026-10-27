"""Adaptador PostgreSQL limitado a notificaciones del usuario actual."""

from __future__ import annotations

from datetime import datetime

import psycopg


class PostgresNotifications:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def unread_count(self, user_id: int) -> int:
        return self.conn.execute(
            "SELECT count(*) AS n FROM aud.notificacion WHERE usuario_id=%s AND NOT leida",
            (user_id,),
        ).fetchone()["n"]

    def list(self, user_id: int, only_unread: bool, before: tuple[datetime, int] | None,
             limit: int) -> list[dict]:
        return self.conn.execute(
            "SELECT id,titulo,cuerpo,enlace,tipo,leida,creado_en FROM aud.notificacion "
            "WHERE usuario_id=%s AND (NOT %s OR NOT leida) "
            "AND (%s::timestamptz IS NULL OR (creado_en,id)<(%s,%s)) "
            "ORDER BY creado_en DESC,id DESC LIMIT %s",
            (user_id, only_unread, before[0] if before else None,
             before[0] if before else None, before[1] if before else None, limit),
        ).fetchall()

    def mark_read(self, user_id: int, notification_id: int) -> bool:
        return self.conn.execute(
            "UPDATE aud.notificacion SET leida=true WHERE id=%s AND usuario_id=%s",
            (notification_id, user_id),
        ).rowcount == 1

    def mark_all_read(self, user_id: int) -> None:
        self.conn.execute(
            "UPDATE aud.notificacion SET leida=true WHERE usuario_id=%s AND NOT leida",
            (user_id,),
        )
