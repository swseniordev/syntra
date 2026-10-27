"""Certificado HTTPS de desarrollo, autofirmado y limitado al loopback."""

from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main() -> None:
    folder = Path(os.environ["LOCALAPPDATA"]) / "Syntra" / "certs"
    keyfile, certfile = folder / "local-key.pem", folder / "local-cert.pem"
    if keyfile.exists() or certfile.exists():
        raise SystemExit("El certificado local ya existe; no se sobrescribe")
    folder.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Syntra local")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Syntra local")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    with keyfile.open("xb") as handle:
        handle.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with certfile.open("xb") as handle:
        handle.write(cert.public_bytes(serialization.Encoding.PEM))
    print("Certificado HTTPS local creado fuera del repositorio.")


if __name__ == "__main__":
    main()
