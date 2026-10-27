"""Caso de uso de alta inicial del administrador de Syntra."""

from __future__ import annotations

from typing import Any, Protocol, Self

from app.modules.usuarios.domain.rules import InvalidUser, normalize


class BootstrapAdminProblem(Exception):
    """La inicialización del primer administrador no puede continuar."""


class BootstrapAudit(Protocol):
    def record(self, *, actor_id: int | None, module: str, action: str, entity_type: str,
               entity_id: str | None, entity_name: str | None = None,
               before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
               detail: str | None = None) -> None: ...


class BootstrapAdminUnitOfWork(Protocol):
    audit: BootstrapAudit

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...
    def lock_users(self) -> None: ...
    def email_exists(self, email: str) -> bool: ...
    def has_users(self) -> bool: ...
    def admin_role(self) -> tuple[str, int, int] | None: ...
    def create_admin(self, name: str, email: str, password_hash: str) -> dict[str, Any]: ...
    def preflight(self) -> dict[str, Any]: ...
    def commit(self) -> None: ...


class BootstrapAdmin:
    """Crea un único Administrador activo, sin correo ni cambios de RBAC."""

    def __init__(self, uow: BootstrapAdminUnitOfWork):
        self.uow = uow

    def preflight(self) -> dict[str, Any]:
        """Comprueba preparación sin bloquear tablas ni confirmar escrituras."""
        with self.uow:
            result = self.uow.preflight()
        expected_role = {"nombre": "Administrador", "estado_id": 1, "permisos": 67}
        result["ready"] = (
            result.get("database") == "syntra"
            and result.get("current_user") == "syntra_api_login"
            and result.get("session_user") == "syntra_api_login"
            and result.get("superuser") is False
            and result.get("tables", {}) and all(result["tables"].values())
            and result.get("privileges", {}) and all(result["privileges"].values())
            and result.get("has_users") is False
            and result.get("admin_role") == expected_role
        )
        return result

    def create(self, name: str, email: str, password_hash: str) -> int:
        try:
            values = normalize({"nombre": name, "email": email})
        except InvalidUser as exc:
            raise BootstrapAdminProblem(str(exc)) from None
        if not isinstance(password_hash, str) or not password_hash.startswith("$argon2id$"):
            raise BootstrapAdminProblem("La credencial debe estar codificada con Argon2id")

        with self.uow:
            self.uow.lock_users()
            if self.uow.email_exists(values["email"]):
                raise BootstrapAdminProblem("Ya existe un usuario con ese correo; no se modificó")
            if self.uow.has_users():
                raise BootstrapAdminProblem("Ya existe un usuario; el bootstrap inicial ya no está disponible")
            if self.uow.admin_role() != ("Administrador", 1, 67):
                raise BootstrapAdminProblem("El rol Administrador activo con sus 67 permisos aprobados no está preparado")

            row = self.uow.create_admin(values["nombre"], values["email"], password_hash)
            self.uow.audit.record(
                actor_id=row["id"], module="usuarios", action="crear", entity_type="Usuario",
                entity_id=str(row["id"]), entity_name=row["nombre"],
                after={"id": row["id"], "nombre": row["nombre"], "email": row["email"],
                       "rol_id": 1, "estado_id": 1},
                detail="primer_administrador",
            )
            self.uow.commit()
            return row["id"]
