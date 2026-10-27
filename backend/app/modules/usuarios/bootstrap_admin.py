"""Comando interactivo para crear el primer administrador en una instalación QA."""

from __future__ import annotations

import getpass
import argparse

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings
from app.core.security import password_hasher
from app.modules.usuarios.application.bootstrap import BootstrapAdmin, BootstrapAdminProblem
from app.modules.usuarios.infrastructure.bootstrap_postgres import PostgresBootstrapAdminUnitOfWork


def _read_input(input_fn=input, secret_input=getpass.getpass) -> tuple[str, str, str]:
    name = input_fn("Nombre del administrador: ").strip()
    email = input_fn("Correo del administrador: ").strip()
    password = secret_input("Contraseña elegida para el administrador: ")
    confirmation = secret_input("Repetir contraseña: ")
    if password != confirmation or len(password) < 12:
        raise BootstrapAdminProblem("Las contraseñas deben coincidir y tener al menos 12 caracteres")
    return name, email, password


def _connect():
    if settings.database_name != "syntra":
        raise SystemExit("Este comando está restringido a la base QA syntra")
    if settings.database_user != "syntra_api_login":
        raise SystemExit("El bootstrap requiere la conexión configurada como syntra_api_login")
    return psycopg.connect(
        host=settings.database_host, port=settings.database_port, dbname=settings.database_name,
        user=settings.database_user, passfile=str(settings.database_passfile), connect_timeout=5,
        application_name="syntra_admin_bootstrap", row_factory=dict_row,
    )


def _print_preflight(result: dict) -> None:
    print(f"Base: {result.get('database', 'no verificada')}")
    print(f"Identidad: current_user={result.get('current_user', 'no verificado')}; "
          f"session_user={result.get('session_user', 'no verificado')}; "
          f"superusuario={result.get('superuser', 'no verificado')}")
    print("Tablas requeridas: " + ", ".join(
        f"{name}={'OK' if present else 'FALTA'}" for name, present in result.get("tables", {}).items()
    ))
    print("Privilegios efectivos: " + ", ".join(
        f"{name}={'OK' if allowed else 'FALTA'}" for name, allowed in result.get("privileges", {}).items()
    ))
    role = result.get("admin_role")
    if role is None:
        print("Rol Administrador: no verificado")
    else:
        print(f"Rol Administrador: nombre={role['nombre']}; estado_id={role['estado_id']}; "
              f"permisos={role['permisos']}")
    user_status = result.get("has_users")
    print("Usuarios existentes: " + ("sí; bootstrap bloqueado" if user_status else
          "ninguno" if user_status is False else "no verificado"))


def _run_preflight() -> dict:
    try:
        with _connect() as conn:
            return BootstrapAdmin(PostgresBootstrapAdminUnitOfWork(conn)).preflight()
    except (psycopg.Error, SystemExit) as exc:
        if isinstance(exc, SystemExit):
            raise
        raise SystemExit(f"Prevalidación fallida ({type(exc).__name__}); no se efectuaron escrituras") from None


def main() -> None:
    parser = argparse.ArgumentParser(description="Prevalidar o crear el primer administrador de Syntra QA")
    parser.add_argument("--check", action="store_true", help="consulta solo lectura; no solicita credenciales")
    args = parser.parse_args()

    if args.check:
        result = _run_preflight()
        _print_preflight(result)
        if not result.get("ready"):
            raise SystemExit("PREVALIDACIÓN NO APROBADA; no ejecutar el alta")
        print("PREVALIDACIÓN APROBADA; no se efectuaron escrituras.")
        return

    result = _run_preflight()
    _print_preflight(result)
    if not result.get("ready"):
        raise SystemExit("PREVALIDACIÓN NO APROBADA; no se solicitaron credenciales ni se creó el administrador")

    try:
        name, email, password = _read_input()
    except BootstrapAdminProblem as exc:
        raise SystemExit(str(exc)) from None

    password_hash = password_hasher.hash(password)
    del password
    try:
        with _connect() as conn:
            identifier = BootstrapAdmin(PostgresBootstrapAdminUnitOfWork(conn)).create(
                name, email, password_hash,
            )
    except BootstrapAdminProblem as exc:
        raise SystemExit(str(exc)) from None
    except (psycopg.Error, ValueError, SystemExit) as exc:
        if isinstance(exc, SystemExit):
            raise
        # No imprimir el detalle del driver, que puede contener SQL o parámetros.
        raise SystemExit(f"No se creó el administrador; la transacción se revirtió ({type(exc).__name__})") from None
    finally:
        del password_hash

    print(f"Administrador inicial creado y auditado (id={identifier}); no se envió correo.")


if __name__ == "__main__":
    main()
