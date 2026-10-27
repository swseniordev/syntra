"""Persistencia PostgreSQL de Cuentas; wrapper DDL y auditoría comparten transacción."""

from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.errors import LockNotAvailable, DeadlockDetected, UniqueViolation

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter
from app.modules.cuentas.application.ports import Account, DuplicateAccount, ProvisioningBusy

FIELDS = ("c.id,c.cliente_id,cl.nombre AS cliente_nombre,c.nombre,c.actor_principal,c.entidad,c.taxonomia,"
          "c.prompt_clusters,c.prompt_temas,c.estado_id,c.creado_en,c.creado_por,"
          "c.actualizado_en,c.actualizado_por")
EDITABLE = frozenset({"cliente_id", "nombre", "actor_principal", "entidad", "taxonomia",
                      "prompt_clusters", "prompt_temas", "estado_id"})


class PostgresAccountRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _visibility(self, actor_id: int, global_access: bool) -> tuple[str, list[object]]:
        if global_access:
            return "", []
        return (" AND EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v "
                "WHERE v.cuenta_id=c.id AND v.usuario_id=%s)", [actor_id])

    def list(self, query: str, state: str, client_id: int | None, after_id: int | None, limit: int,
             actor_id: int, global_access: bool) -> tuple[int, list[Account]]:
        clauses = [{"vigentes": "c.estado_id<>-1", "activos": "c.estado_id=1",
                    "inactivos": "c.estado_id=0", "eliminados": "c.estado_id=-1"}[state]]
        args: list[object] = []
        if not global_access:
            clauses.append("EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v WHERE v.cuenta_id=c.id AND v.usuario_id=%s)")
            args.append(actor_id)
        if client_id is not None:
            clauses.append("c.cliente_id=%s")
            args.append(client_id)
        if query:
            clauses.append("c.nombre ILIKE %s")
            args.append(f"%{query}%")
        total = self.conn.execute(f"SELECT count(*) AS n FROM cfg.cuenta c WHERE {' AND '.join(clauses)}", args).fetchone()["n"]
        if after_id is not None:
            clauses.append("c.id>%s")
            args.append(after_id)
        rows = self.conn.execute(
            f"SELECT {FIELDS} FROM cfg.cuenta c JOIN cfg.cliente cl ON cl.id=c.cliente_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY c.id LIMIT %s",
            (*args, limit),
        ).fetchall()
        return total, rows

    def get(self, account_id: int, actor_id: int, global_access: bool, *, for_update: bool = False) -> Account | None:
        visibility, args = self._visibility(actor_id, global_access)
        return self.conn.execute(
            f"SELECT {FIELDS} FROM cfg.cuenta c JOIN cfg.cliente cl ON cl.id=c.cliente_id "
            f"WHERE c.id=%s{visibility}" + (" FOR UPDATE OF c" if for_update else ""),
            (account_id, *args),
        ).fetchone()

    def client_state(self, client_id: int) -> int | None:
        row = self.conn.execute("SELECT estado_id FROM cfg.cliente WHERE id=%s", (client_id,)).fetchone()
        return row["estado_id"] if row else None

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        return self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM cfg.cuenta WHERE lower(nombre)=lower(%s) AND estado_id<>-1 "
            "AND (%s::int IS NULL OR id<>%s::int)) AS existe", (name, exclude_id, exclude_id),
        ).fetchone()["existe"]

    def create(self, values: Account, actor_id: int) -> Account:
        try:
            identifier = self.conn.execute(
                "INSERT INTO cfg.cuenta(cliente_id,nombre,actor_principal,entidad,taxonomia,prompt_clusters,prompt_temas,"
                "estado_id,creado_por,actualizado_por) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (values["cliente_id"], values["nombre"], values.get("actor_principal"), values.get("entidad"),
                 values.get("taxonomia"), values["prompt_clusters"], values["prompt_temas"],
                 values.get("estado_id", 1), actor_id, actor_id),
            ).fetchone()["id"]
        except UniqueViolation:
            raise DuplicateAccount from None
        return self.get(identifier, actor_id, True)

    def provision(self, account_id: int, actor_id: int) -> None:
        try:
            self.conn.execute("SELECT ops.fn_aprovisionar_cuenta(%s,%s)", (account_id, actor_id))
        except (LockNotAvailable, DeadlockDetected):
            raise ProvisioningBusy from None

    def update(self, account_id: int, values: Account, actor_id: int) -> Account:
        fields = {key: value for key, value in values.items() if key in EDITABLE}
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields]
        assignments.extend((sql.SQL("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')"),
                            sql.SQL("actualizado_por=%s")))
        statement = sql.SQL("UPDATE cfg.cuenta SET {} WHERE id=%s RETURNING id").format(sql.SQL(",").join(assignments))
        try:
            self.conn.execute(statement, (*fields.values(), actor_id, account_id))
        except UniqueViolation:
            raise DuplicateAccount from None
        return self.get(account_id, actor_id, True)


class PostgresAccountUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.accounts = PostgresAccountRepository(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresAccountUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
