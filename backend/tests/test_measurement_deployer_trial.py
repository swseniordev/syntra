"""Ensayo administrativo de Entrega 5 en clúster PostgreSQL descartable."""

from pathlib import Path
import socket
import subprocess
import tempfile

import psycopg
import pytest


@pytest.mark.skipif(__import__("os").getenv("SYNTRA_RUN_DB_INTEGRATION") != "1",
                    reason="Requiere activar explícitamente PostgreSQL descartable")
def test_restricted_deployer_can_run_measurement_migration_without_superuser():
    root = Path(__file__).resolve().parents[2]
    pg = Path("C:/Program Files/PostgreSQL/18/bin")
    temp_parent = root / "backend" / ".test-db"
    temp_parent.mkdir(exist_ok=True)

    def run(*args, input_text=None):
        background = Path(args[0]).name.lower() == "pg_ctl.exe"
        result = subprocess.run(args, input=input_text,
                                stdout=subprocess.DEVNULL if background else subprocess.PIPE,
                                stderr=subprocess.DEVNULL if background else subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", timeout=120, check=False)
        assert result.returncode == 0, f"{Path(args[0]).name} falló: {(result.stderr or '')[-1500:]}"
        return result

    with tempfile.TemporaryDirectory(prefix="syntra_deployer_", dir=temp_parent) as folder:
        work = Path(folder)
        data = work / "data"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        run(str(pg / "initdb.exe"), "-D", str(data), "-U", "postgres", "-A", "trust",
            "--encoding=UTF8", "--no-instructions")
        started = False
        try:
            run(str(pg / "pg_ctl.exe"), "-D", str(data), "-l", str(work / "postgres.log"),
                "-o", f"-h 127.0.0.1 -p {port}", "-w", "start")
            started = True
            with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres",
                                 user="postgres", autocommit=True, connect_timeout=5) as conn:
                conn.execute("CREATE DATABASE syntra_trial")
            common = ("-X", "-w", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
                      "-p", str(port), "-U", "postgres", "-d", "syntra_trial")
            for script in (
                root / ".syntra-init-trial-20261020" / "ddl_trial.sql",
                root / ".syntra-init-trial-20261020" / "catalogos_tecnicos_trial.sql",
                root / "database" / "initialize_api_role.sql",
                root / "database" / "entrega3_cuentas_aprovisionamiento.sql",
            ):
                run(str(pg / "psql.exe"), *common, "-f", str(script))
            run(str(pg / "psql.exe"), *common, "-v", "TARGET_DB=syntra_trial",
                "-f", str(root / "database" / "entrega5_preparar_deployer.sql"))
            with psycopg.connect(host="127.0.0.1", port=port, dbname="syntra_trial",
                                 user="postgres", connect_timeout=5) as conn:
                role = conn.execute("SELECT rolcanlogin,rolsuper,rolcreaterole FROM pg_roles "
                                    "WHERE rolname='syntra_mediciones_deployer'").fetchone()
                assert role == (False, False, False)
                assert conn.execute("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE "
                                    "oid='ops.fn_preparar_medicion(integer,integer,integer[])'::regprocedure").fetchone()[0] == "syntra_mediciones_deployer"
                assert conn.execute("SELECT has_schema_privilege('syntra_api_login','med','USAGE')").fetchone()[0] is False
            migration = root / "database" / "entrega5_mediciones.sql"
            command = (f"SET ROLE syntra_mediciones_deployer;\n"
                       f"\\i '{migration.as_posix()}'\n")
            run(str(pg / "psql.exe"), *common, "-v", "SLA_100K_S=180",
                "-v", "SLA_1M_S=1799", "-v", "MED_TIMEOUT_MS=1799000", "-f", "-",
                input_text=command)
            with psycopg.connect(host="127.0.0.1", port=port, dbname="syntra_trial",
                                 user="postgres", connect_timeout=5) as conn:
                assert conn.execute("SELECT has_schema_privilege('syntra_api_login','med','USAGE')").fetchone()[0] is True
                assert conn.execute("SELECT max_intentos,backoff_base_ms,backoff_max_ms,timeout_ms "
                                    "FROM ops.politica_reintento WHERE operacion='preparar_medicion'").fetchone() == (3, 30000, 120000, 1799000)
                assert conn.execute("SELECT rolcanlogin,rolsuper,rolcreaterole FROM pg_roles "
                                    "WHERE rolname='syntra_measurement_worker_login'").fetchone() == (True, False, False)
                assert conn.execute("SELECT pg_get_userbyid(datdba) FROM pg_database "
                                    "WHERE datname='syntra_trial'").fetchone()[0] == "postgres"
        finally:
            if started:
                run(str(pg / "pg_ctl.exe"), "-D", str(data), "-m", "immediate", "-w", "stop")
