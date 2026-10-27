"""Una vez: clave aleatoria del rol API en passfile privado y par RS256 local.

La cuenta postgres se autentica con el pgpass existente; jamás se imprime un secreto.
"""

import os
from pathlib import Path
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import psycopg
from psycopg import sql

from app.core.config import settings


def main() -> None:
    postgres_passfile = Path(os.environ["APPDATA"]) / "postgresql" / "pgpass.conf"
    if not postgres_passfile.is_file():
        raise RuntimeError("No se encontró pgpass.conf para postgres")
    if settings.database_passfile.exists():
        raise RuntimeError("Ya existe el passfile del rol API; no se sobrescribe")
    with psycopg.connect(
        host=settings.database_host, port=settings.database_port, dbname=settings.database_name,
        user="postgres", passfile=str(postgres_passfile),
    ) as conn:
        role = conn.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='syntra_api_login'").fetchone()
        if role != (False,):
            raise RuntimeError("El rol API no está en el estado NOLOGIN esperado")
        password = secrets.token_urlsafe(48)
        verifier = conn.pgconn.encrypt_password(password.encode(), b"syntra_api_login", b"scram-sha-256").decode()
        settings.database_passfile.parent.mkdir(parents=True, exist_ok=True)
        line = f"{settings.database_host}:{settings.database_port}:{settings.database_name}:syntra_api_login:{password}\n"
        with settings.database_passfile.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
        try:
            conn.execute(sql.SQL("ALTER ROLE syntra_api_login LOGIN PASSWORD {}").format(sql.Literal(verifier)))
            conn.commit()
        except Exception:
            settings.database_passfile.unlink(missing_ok=True)
            raise
    with psycopg.connect(
        host=settings.database_host, port=settings.database_port, dbname=settings.database_name,
        user="syntra_api_login", passfile=str(settings.database_passfile),
    ) as conn:
        connected = conn.execute("SELECT current_user").fetchone()[0]
        if connected != "syntra_api_login":
            raise RuntimeError("No se verificó la conexión del rol API")
    settings.jwt_private_key.parent.mkdir(parents=True, exist_ok=True)
    if not settings.jwt_private_key.exists():
        private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        data = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with settings.jwt_private_key.open("xb") as handle:
            handle.write(data)
    print("Rol API con LOGIN verificado; clave y llave JWT guardadas fuera del repositorio.")


if __name__ == "__main__":
    main()
