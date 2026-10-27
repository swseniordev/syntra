"""Adaptador PostgreSQL para el bootstrap de Usuarios."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.errors import UniqueViolation

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter


class PostgresBootstrapAdminUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresBootstrapAdminUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def lock_users(self) -> None:
        self.conn.execute("LOCK TABLE seg.usuario IN SHARE ROW EXCLUSIVE MODE")

    def email_exists(self, email: str) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM seg.usuario WHERE lower(email)=lower(%s)) AS email_exists",
            (email,),
        ).fetchone()["email_exists"]

    def has_users(self) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM seg.usuario) AS has_users",
        ).fetchone()["has_users"]

    def admin_role(self) -> tuple[str, int, int] | None:
        row = self.conn.execute(
            "SELECT r.nombre,r.estado_id,count(p.rol_id)::int AS permisos "
            "FROM seg.rol r LEFT JOIN seg.rol_permiso p ON p.rol_id=r.id "
            "WHERE r.id=1 GROUP BY r.id,r.nombre,r.estado_id",
        ).fetchone()
        if row is None:
            return None
        return row["nombre"], row["estado_id"], row["permisos"]

    def create_admin(self, name: str, email: str, password_hash: str) -> dict[str, Any]:
        try:
            row = self.conn.execute(
                "INSERT INTO seg.usuario(nombre,email,password_hash,rol_id,estado_id) "
                "VALUES (%s,%s,%s,1,1) RETURNING id,nombre,email,rol_id,estado_id",
                (name, email, password_hash),
            ).fetchone()
        except UniqueViolation:
            raise ValueError("Conflicto al crear el usuario") from None
        return row

    def preflight(self) -> dict[str, Any]:
        # Primer comando de la transacción: el modo read-only impide escrituras
        # accidentales durante esta comprobación operativa.
        self.conn.execute("SET TRANSACTION READ ONLY")
        identity = self.conn.execute(
            "SELECT current_database() AS database,current_user AS current_user,"
            "session_user AS session_user,COALESCE((SELECT rolsuper FROM pg_roles "
            "WHERE rolname=current_user),true) AS superuser",
        ).fetchone()
        relations = self.conn.execute(
            "SELECT to_regclass('seg.usuario') IS NOT NULL AS usuario,"
            "to_regclass('seg.rol') IS NOT NULL AS rol,"
            "to_regclass('seg.rol_permiso') IS NOT NULL AS rol_permiso,"
            "to_regclass('aud.auditoria') IS NOT NULL AS auditoria",
        ).fetchone()
        result: dict[str, Any] = {**identity, "tables": dict(relations)}
        if not all(result["tables"].values()):
            result.update(privileges={}, has_users=None, admin_role=None)
            return result

        result["privileges"] = self.conn.execute(
            "SELECT has_schema_privilege(current_user,'seg','USAGE') AS seg_usage,"
            "has_schema_privilege(current_user,'aud','USAGE') AS aud_usage,"
            "has_table_privilege(current_user,'seg.usuario','SELECT') AS usuario_select,"
            # The following lock needs one of these table-level rights; the
            # per-column INSERT grants checked below do not authorize it.
            "has_table_privilege(current_user,'seg.usuario',"
            "'MAINTAIN,UPDATE,DELETE,TRUNCATE') AS usuario_lock,"
            "has_column_privilege(current_user,'seg.usuario','nombre','INSERT') AS usuario_nombre_insert,"
            "has_column_privilege(current_user,'seg.usuario','email','INSERT') AS usuario_email_insert,"
            "has_column_privilege(current_user,'seg.usuario','password_hash','INSERT') AS usuario_hash_insert,"
            "has_column_privilege(current_user,'seg.usuario','rol_id','INSERT') AS usuario_rol_insert,"
            "has_column_privilege(current_user,'seg.usuario','estado_id','INSERT') AS usuario_estado_insert,"
            "has_table_privilege(current_user,'seg.rol','SELECT') AS rol_select,"
            "has_table_privilege(current_user,'seg.rol_permiso','SELECT') AS permiso_select,"
            "has_table_privilege(current_user,'aud.auditoria','INSERT') AS auditoria_insert",
        ).fetchone()
        result["has_users"] = self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM seg.usuario) AS has_users",
        ).fetchone()["has_users"]
        role = self.conn.execute(
            "SELECT r.nombre,r.estado_id,count(p.rol_id)::int AS permisos "
            "FROM seg.rol r LEFT JOIN seg.rol_permiso p ON p.rol_id=r.id "
            "WHERE r.id=1 GROUP BY r.id,r.nombre,r.estado_id",
        ).fetchone()
        result["admin_role"] = role
        return result

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
