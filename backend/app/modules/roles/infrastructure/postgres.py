"""Persistencia de Roles y permisos en una única transacción."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter
from app.modules.roles.application.ports import DuplicateRoleName, RoleRow
from app.modules.roles.domain.rules import APPROVED_PAIRS

FIELDS = "id,nombre,descripcion,ver_todas,estado_id,creado_en,creado_por,actualizado_en,actualizado_por"


class PostgresRoleRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _with_permissions(self, rows: list[RoleRow]) -> list[RoleRow]:
        if not rows:
            return rows
        ids = [row["id"] for row in rows]
        permissions = self.conn.execute(
            "SELECT rol_id,modulo,accion FROM seg.rol_permiso WHERE rol_id=ANY(%s) ORDER BY modulo,accion", (ids,),
        ).fetchall()
        by_role: dict[int, dict[str, list[str]]] = {role_id: {} for role_id in ids}
        for item in permissions:
            by_role[item["rol_id"]].setdefault(item["modulo"], []).append(item["accion"])
        for row in rows:
            row["permisos"] = by_role[row["id"]]
        return rows

    def list(self, query: str, state: str, after_id: int | None, limit: int) -> tuple[int, list[RoleRow]]:
        clauses = [{"vigentes": "estado_id<>-1", "activos": "estado_id=1", "inactivos": "estado_id=0", "eliminados": "estado_id=-1"}[state]]
        args: list[object] = []
        if query:
            clauses.append("(nombre ILIKE %s OR descripcion ILIKE %s)")
            args.extend((f"%{query}%", f"%{query}%"))
        total = self.conn.execute(f"SELECT count(*) AS n FROM seg.rol WHERE {' AND '.join(clauses)}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("id>%s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM seg.rol WHERE {' AND '.join(clauses)} ORDER BY id LIMIT %s", (*args, limit),
        ).fetchall()
        return total, self._with_permissions(rows)

    def get(self, role_id: int, *, for_update: bool = False) -> RoleRow | None:
        row = self.conn.execute(
            f"SELECT {FIELDS} FROM seg.rol WHERE id=%s" + (" FOR UPDATE" if for_update else ""), (role_id,),
        ).fetchone()
        return self._with_permissions([row])[0] if row else None

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM seg.rol WHERE lower(nombre)=lower(%s) AND estado_id<>-1 "
            "AND (%s::int IS NULL OR id<>%s::int)) AS existe", (name, exclude_id, exclude_id),
        ).fetchone()["existe"]

    def has_users(self, role_id: int) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM seg.usuario WHERE rol_id=%s AND estado_id<>-1) AS existe", (role_id,),
        ).fetchone()["existe"]

    def is_assigned_to(self, role_id: int, user_id: int) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM seg.usuario WHERE rol_id=%s AND id=%s AND estado_id<>-1) AS existe",
            (role_id, user_id),
        ).fetchone()["existe"]

    def _replace_permissions(self, role_id: int, permissions: frozenset[tuple[str, str]]) -> None:
        self.conn.execute("DELETE FROM seg.rol_permiso WHERE rol_id=%s", (role_id,))
        for module, action in sorted(permissions):
            self.conn.execute(
                "INSERT INTO seg.rol_permiso(rol_id,modulo,accion) VALUES (%s,%s,%s)", (role_id, module, action),
            )

    def create(self, values: RoleRow, permissions: frozenset[tuple[str, str]], actor_id: int) -> RoleRow:
        try:
            row = self.conn.execute(
                f"""INSERT INTO seg.rol(nombre,descripcion,ver_todas,estado_id,creado_por,actualizado_por)
                     VALUES (%s,%s,%s,%s,%s,%s) RETURNING {FIELDS}""",
                (values["nombre"], values.get("descripcion"), values.get("ver_todas", False), values.get("estado_id", 1), actor_id, actor_id),
            ).fetchone()
            self._replace_permissions(row["id"], permissions)
        except UniqueViolation:
            raise DuplicateRoleName from None
        return self.get(row["id"])

    def update(self, role_id: int, changes: RoleRow, permissions: frozenset[tuple[str, str]] | None, actor_id: int) -> RoleRow:
        fields = {key: value for key, value in changes.items() if key in {"nombre", "descripcion", "ver_todas", "estado_id"}}
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields]
        assignments.extend((sql.SQL("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"),
                            sql.SQL("actualizado_por=%s")))
        statement = sql.SQL("UPDATE seg.rol SET {} WHERE id=%s RETURNING id").format(sql.SQL(",").join(assignments))
        try:
            self.conn.execute(statement, (*fields.values(), actor_id, role_id))
            if permissions is not None:
                self._replace_permissions(role_id, permissions)
        except UniqueViolation:
            raise DuplicateRoleName from None
        return self.get(role_id)

    def set_state(self, role_id: int, state: int, actor_id: int) -> RoleRow:
        return self.update(role_id, {"estado_id": state}, None, actor_id)

    def catalog(self) -> list[dict[str, str]]:
        modules = {row["codigo"]: row["nombre"] for row in self.conn.execute("SELECT codigo,nombre FROM cat.modulo")}
        actions = {row["codigo"]: row["nombre"] for row in self.conn.execute("SELECT codigo,nombre FROM cat.accion")}
        if any(module not in modules or action not in actions for module, action in APPROVED_PAIRS):
            raise RuntimeError("El catálogo técnico no contiene los 67 pares aprobados")
        return [
            {"modulo": module, "modulo_nombre": modules[module], "accion": action, "accion_nombre": actions[action]}
            for module, action in sorted(APPROVED_PAIRS)
        ]


class PostgresRoleUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.roles = PostgresRoleRepository(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresRoleUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
