"""Persistencia PostgreSQL de usuarios, sesiones y permisos."""

from datetime import datetime
import uuid

import psycopg


class PostgresAuthStore:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def lock_login_user(self, email: str) -> dict | None:
        return self.conn.execute(
            """SELECT u.id,u.email,u.password_hash,u.rol_id,u.version_token,u.estado_id,
                      u.intentos_fallidos,u.bloqueado_hasta,r.ver_todas,r.estado_id AS rol_estado
                 FROM seg.usuario u JOIN seg.rol r ON r.id=u.rol_id
                WHERE lower(u.email)=lower(%s) AND u.estado_id<>-1 FOR UPDATE OF u""",
            (email,),
        ).fetchone()

    def failed_login(self, user_id: int, failures: int, blocked_until: datetime | None) -> None:
        self.conn.execute("UPDATE seg.usuario SET intentos_fallidos=%s,bloqueado_hasta=%s WHERE id=%s", (failures, blocked_until, user_id))

    def successful_login(self, user_id: int, now: datetime) -> None:
        self.conn.execute("UPDATE seg.usuario SET intentos_fallidos=0,bloqueado_hasta=NULL,ultimo_acceso=%s WHERE id=%s", (now, user_id))

    def create_session(self, session_id: uuid.UUID, family_id: uuid.UUID, user_id: int, token_hash: bytes, expires: datetime, ip: str | None, user_agent: str | None) -> None:
        self.conn.execute(
            """INSERT INTO seg.sesion(id,familia_id,usuario_id,refresh_hash,expira_en,ip,user_agent)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (session_id, family_id, user_id, token_hash, expires, ip, user_agent),
        )

    def permissions(self, role_id: int) -> list[str]:
        return [f"{p['modulo']}:{p['accion']}" for p in self.conn.execute("SELECT modulo,accion FROM seg.rol_permiso WHERE rol_id=%s", (role_id,))]

    def lock_session(self, session_id: uuid.UUID) -> dict | None:
        return self.conn.execute("SELECT * FROM seg.sesion WHERE id=%s FOR UPDATE", (session_id,)).fetchone()

    def has_active_successor(self, family_id: uuid.UUID) -> bool:
        return self.conn.execute("SELECT 1 FROM seg.sesion WHERE familia_id=%s AND revocado_en IS NULL LIMIT 1", (family_id,)).fetchone() is not None

    def revoke_family(self, family_id: uuid.UUID) -> None:
        self.conn.execute("UPDATE seg.sesion SET revocado_en=now() WHERE familia_id=%s AND revocado_en IS NULL", (family_id,))

    def refresh_user(self, user_id: int) -> dict | None:
        return self.conn.execute(
            """SELECT u.id,u.rol_id,u.version_token,u.estado_id,r.ver_todas,r.estado_id AS rol_estado
                 FROM seg.usuario u JOIN seg.rol r ON r.id=u.rol_id WHERE u.id=%s""",
            (user_id,),
        ).fetchone()

    def revoke_session(self, session_id: uuid.UUID) -> None:
        self.conn.execute("UPDATE seg.sesion SET revocado_en=now() WHERE id=%s", (session_id,))

    def revoke_user_sessions(self, user_id: int) -> None:
        self.conn.execute("UPDATE seg.sesion SET revocado_en=now() WHERE usuario_id=%s AND revocado_en IS NULL", (user_id,))

    def increment_user_version(self, user_id: int) -> None:
        self.conn.execute("UPDATE seg.usuario SET version_token=version_token+1 WHERE id=%s", (user_id,))

    def visible_account_ids(self, user_id: int) -> list[int]:
        return [r["cuenta_id"] for r in self.conn.execute(
            """SELECT DISTINCT v.cuenta_id FROM seg.v_usuario_cuenta v
                 JOIN cfg.cuenta c ON c.id=v.cuenta_id AND c.estado_id<>-1
                WHERE v.usuario_id=%s ORDER BY v.cuenta_id""", (user_id,)
        )]

    def commit(self) -> None:
        self.conn.commit()
