"""Contrato HTTP oficial de notificaciones propias."""

import base64
import binascii
import json
from datetime import datetime

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.db import connection
from app.core.identity import Principal, current_user
from app.modules.notificaciones.application import Notifications
from app.modules.notificaciones.postgres import PostgresNotifications


router = APIRouter(prefix="/api/v1/notificaciones", tags=["Notificaciones"])


def notification_cases(conn: psycopg.Connection = Depends(connection)) -> Notifications:
    return Notifications(PostgresNotifications(conn))


def _before(cursor: str | None) -> tuple[datetime, int] | None:
    if cursor is None:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        created = datetime.fromisoformat(value["creado_en"])
        identifier = value["id"]
        if created.tzinfo is None or type(identifier) is not int or identifier < 1:
            raise ValueError
        return created, identifier
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(400, "Cursor de notificaciones inválido") from None


@router.get("")
def list_notifications(response: Response, solo_no_leidas: bool = False,
                       cursor: str | None = None, limite: int = Query(25, ge=1, le=200),
                       principal: Principal = Depends(current_user),
                       cases: Notifications = Depends(notification_cases)):
    count, items, last = cases.list(principal.user["id"], solo_no_leidas,
                                    _before(cursor), limite)
    if last:
        value = json.dumps({"creado_en": last["creado_en"].isoformat(), "id": last["id"]},
                           separators=(",", ":")).encode()
        response.headers["X-Next-Cursor"] = base64.urlsafe_b64encode(value).decode().rstrip("=")
    response.headers["Cache-Control"] = "private, no-store"
    return {"no_leidas": count, "items": items}


@router.post("/{id}/leer", status_code=204)
def mark_notification(id: int, principal: Principal = Depends(current_user),
                      cases: Notifications = Depends(notification_cases)):
    if not cases.mark_read(principal.user["id"], id):
        raise HTTPException(404, "Notificación no encontrada")
    return Response(status_code=204)


@router.post("/leer-todas", status_code=204)
def mark_all_notifications(principal: Principal = Depends(current_user),
                           cases: Notifications = Depends(notification_cases)):
    cases.mark_all_read(principal.user["id"])
    return Response(status_code=204)
