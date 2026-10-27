"""Lectura de Auditoría para exportación, con cursor del servidor."""

from datetime import datetime
import os


def audit_rows(conn, filters: dict, cutoff: datetime):
    clauses = ["fecha<=%s"]
    args: list[object] = [cutoff]
    for key in ("modulo", "usuario_id", "accion", "entidad_tipo", "entidad_id"):
        if filters.get(key) is not None:
            clauses.append(f"{key}=%s")
            args.append(filters[key])
    if filters.get("desde"):
        clauses.append("fecha>=%s")
        args.append(datetime.fromisoformat(filters["desde"]))
    if filters.get("hasta"):
        clauses.append("fecha<=%s")
        args.append(datetime.fromisoformat(filters["hasta"]))
    if filters.get("q"):
        pattern = "%" + filters["q"] + "%"
        clauses.append("(entidad_nombre ILIKE %s OR entidad_id ILIKE %s OR detalle ILIKE %s)")
        args.extend((pattern, pattern, pattern))
    query = (
        "SELECT fecha,id,usuario_id,modulo,accion,entidad_tipo,entidad_id,entidad_nombre,"
        "antes,despues,detalle,ip,request_id FROM aud.auditoria WHERE " +
        " AND ".join(clauses) + " ORDER BY fecha DESC,id DESC"
    )
    with conn.cursor(name=f"auditoria_export_{os.getpid()}") as cursor:
        cursor.itersize = 1000
        cursor.execute(query, args)
        yield from cursor
