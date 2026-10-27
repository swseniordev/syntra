"""Escritura acotada de Usuarios y tarea de correo en una transacción."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter
from app.modules.usuarios.infrastructure.postgres import FIELDS

EDITABLE = frozenset({"nombre", "email", "telefono", "rol_id", "estado_id", "version_token"})


class PostgresUserWriter:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _groups(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is not None:
            row["grupo_ids"] = [link["grupo_id"] for link in self.conn.execute(
                "SELECT grupo_id FROM seg.grupo_usuario WHERE usuario_id=%s ORDER BY grupo_id", (row["id"],))]
        return row

    def get(self, user_id: int, *, for_update: bool = False) -> dict[str, Any] | None:
        row = self.conn.execute(
            f"SELECT {FIELDS},version_token FROM seg.usuario WHERE id=%s" + (" FOR UPDATE" if for_update else ""),
            (user_id,),
        ).fetchone()
        return self._groups(row)

    def role_authorized(self, role_id: int, permissions: frozenset[str], ver_todas: bool) -> bool:
        role = self.conn.execute(
            "SELECT id,ver_todas FROM seg.rol WHERE id=%s AND estado_id=1 FOR SHARE", (role_id,),
        ).fetchone()
        if role is None or (role["ver_todas"] and not ver_todas):
            return False
        target = {f"{p['modulo']}:{p['accion']}" for p in self.conn.execute(
            "SELECT modulo,accion FROM seg.rol_permiso WHERE rol_id=%s", (role_id,))}
        return target <= permissions

    def groups_exist(self, group_ids: list[int]) -> bool:
        if not group_ids:
            return True
        found = self.conn.execute(
            "SELECT id FROM seg.grupo WHERE id=ANY(%s) AND estado_id<>-1 FOR SHARE", (group_ids,),
        ).fetchall()
        return len(found) == len(group_ids)

    def _links(self, user_id: int, group_ids: list[int]) -> None:
        self.conn.execute(
            "DELETE FROM seg.grupo_usuario WHERE usuario_id=%s AND NOT (grupo_id=ANY(%s))", (user_id, group_ids),
        )
        for group_id in group_ids:
            self.conn.execute(
                "INSERT INTO seg.grupo_usuario(grupo_id,usuario_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (group_id, user_id),
            )

    def create(self, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        try:
            row = self.conn.execute(
                "INSERT INTO seg.usuario(nombre,email,telefono,rol_id,estado_id,creado_por,actualizado_por) "
                "VALUES (%s,%s,%s,%s,1,%s,%s) RETURNING id",
                (values["nombre"], values["email"], values.get("telefono"), values["rol_id"], actor_id, actor_id),
            ).fetchone()
        except UniqueViolation as exc:
            raise ValueError("Ya existe un usuario vigente con ese correo") from exc
        self._links(row["id"], values.get("grupo_ids", []))
        return self.get(row["id"])

    def update(self, user_id: int, values: dict[str, Any], actor_id: int) -> dict[str, Any]:
        fields = {key: value for key, value in values.items() if key in EDITABLE}
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields]
        assignments += [sql.SQL("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"),
                        sql.SQL("actualizado_por=%s")]
        statement = sql.SQL("UPDATE seg.usuario SET {} WHERE id=%s").format(sql.SQL(",").join(assignments))
        try:
            self.conn.execute(statement, (*fields.values(), actor_id, user_id))
        except UniqueViolation as exc:
            raise ValueError("Ya existe un usuario vigente con ese correo") from exc
        if "grupo_ids" in values:
            self._links(user_id, values["grupo_ids"])
        return self.get(user_id)

    def enqueue_password(self, user_id: int, version: int, actor_id: int, reason: str) -> int:
        # Solo IDs y versión esperada; jamás contraseña o hash en payload/opciones.
        process = self.conn.execute(
            "INSERT INTO prc.proceso(tipo,modo,opciones,creado_por,idempotencia) "
            "VALUES ('correo_acceso','manual',%s,%s,%s) RETURNING id",
            (Jsonb({"tipo": "correo_acceso", "motivo": reason}), actor_id, str(uuid4())),
        ).fetchone()
        self.conn.execute(
            "INSERT INTO prc.proceso_tarea(proceso_id,clave,tipo,cola,prioridad,payload) "
            "VALUES (%s,'credencial','correo_acceso','q.notificaciones',1,%s)",
            (process["id"], Jsonb({"usuario_id": user_id, "version_esperada": version, "motivo": reason})),
        )
        return process["id"]

    def revoke_sessions(self, user_id: int) -> None:
        self.conn.execute(
            "UPDATE seg.sesion SET revocado_en=now() WHERE usuario_id=%s AND revocado_en IS NULL", (user_id,),
        )


class PostgresUserUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.users = PostgresUserWriter(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresUserUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
