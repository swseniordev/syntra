"""Lecturas de Usuarios; nunca selecciona hash, sesiones o secretos."""

from __future__ import annotations

import psycopg

FIELDS = ("id,nombre,email,telefono,rol_id,ultimo_acceso,estado_id,"
          "creado_en,creado_por,actualizado_en,actualizado_por")


class PostgresUserReader:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _groups(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return rows
        ids = [row["id"] for row in rows]
        grouped = {identifier: [] for identifier in ids}
        for link in self.conn.execute(
            "SELECT usuario_id,grupo_id FROM seg.grupo_usuario WHERE usuario_id=ANY(%s) ORDER BY grupo_id", (ids,),
        ):
            grouped[link["usuario_id"]].append(link["grupo_id"])
        for row in rows:
            row["grupo_ids"] = grouped[row["id"]]
        return rows

    def list(self, query: str, state: str, role_id: int | None, after_id: int | None, limit: int) -> tuple[int, list[dict]]:
        clauses = [{"vigentes": "estado_id<>-1", "activos": "estado_id=1",
                    "inactivos": "estado_id=0", "eliminados": "estado_id=-1"}[state]]
        args: list[object] = []
        if query:
            clauses.append("(nombre ILIKE %s OR email ILIKE %s)")
            args.extend((f"%{query}%", f"%{query}%"))
        if role_id is not None:
            clauses.append("rol_id=%s")
            args.append(role_id)
        total = self.conn.execute(f"SELECT count(*) AS n FROM seg.usuario WHERE {' AND '.join(clauses)}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("id>%s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM seg.usuario WHERE {' AND '.join(clauses)} ORDER BY id LIMIT %s", (*args, limit),
        ).fetchall()
        return total, self._groups(rows)

    def get(self, user_id: int) -> dict | None:
        row = self.conn.execute(f"SELECT {FIELDS} FROM seg.usuario WHERE id=%s", (user_id,)).fetchone()
        return self._groups([row])[0] if row else None
