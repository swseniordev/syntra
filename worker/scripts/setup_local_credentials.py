"""Activa una identidad técnica del worker local sin revelar el secreto generado.

Uso: python scripts/setup_local_credentials.py reportes|correo|mediciones|ingesta
El archivo pgpass queda fuera del repositorio. No sobrescribe credenciales existentes.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import sys

import psycopg
from psycopg import sql
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.private_files import restrict_to_current_user


ROLES = {
    "reportes": ("syntra_report_worker_login", "syntra_report_pgpass.conf"),
    "correo": ("syntra_mail_worker_login", "syntra_mail_pgpass.conf"),
    "mediciones": ("syntra_measurement_worker_login", "syntra_measurement_pgpass.conf"),
    "ingesta": ("syntra_ingest_worker_login", "syntra_ingest_pgpass.conf"),
}


def setup(queue: str) -> Path:
    role, filename = ROLES[queue]
    appdata = Path(os.environ["APPDATA"]).resolve()
    postgres_file = appdata / "postgresql" / "pgpass.conf"
    private_file = appdata / "postgresql" / filename
    if not postgres_file.is_file():
        raise RuntimeError("Falta pgpass.conf de la cuenta administradora local")
    if private_file.exists():
        raise RuntimeError("El archivo de credenciales del worker ya existe; no se sobrescribe")
    host = os.getenv("SYNTRA_DB_HOST", "127.0.0.1")
    port = int(os.getenv("SYNTRA_DB_PORT", "5432"))
    database = os.getenv("SYNTRA_DB_NAME", "syntra_dev")
    if host != "127.0.0.1" or database != "syntra_dev":
        raise RuntimeError("Este aprovisionador solo admite la base local syntra_dev")
    with psycopg.connect(host=host, port=port, dbname=database, user="postgres",
                         passfile=str(postgres_file), connect_timeout=5) as admin:
        existing = admin.execute(
            "SELECT rolcanlogin,rolpassword IS NULL FROM pg_authid WHERE rolname=%s", (role,)
        ).fetchone()
        expected = (True, True) if queue in ("mediciones", "ingesta") else (False, True)
        if existing != expected:
            raise RuntimeError("El rol no está en el estado inicial sin credencial esperado")
        password = secrets.token_urlsafe(48)
        verifier = admin.pgconn.encrypt_password(password.encode(), role.encode(), b"scram-sha-256").decode()
        try:
            with private_file.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{host}:{port}:{database}:{role}:{password}\n")
            restrict_to_current_user(private_file)
            admin.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(verifier)))
            admin.commit()
        except Exception:
            private_file.unlink(missing_ok=True)
            raise
    with psycopg.connect(host=host, port=port, dbname=database, user=role,
                         passfile=str(private_file), connect_timeout=5) as limited:
        if limited.execute("SELECT current_user").fetchone()[0] != role:
            raise RuntimeError("No se pudo comprobar la conexión del rol limitado")
    return private_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue", choices=sorted(ROLES))
    selected = parser.parse_args().queue
    setup(selected)
    print("Conexión del worker verificada; credencial privada guardada fuera del repositorio.")
