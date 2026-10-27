"""Adaptador a la criptografía compartida de app.core."""

from argon2.exceptions import VerificationError

from app.core.security import new_refresh, password_hasher, refresh_identity, sign_access

_DUMMY_HASH = password_hasher.hash("syntra-dummy-password-never-valid")


class CoreAuthCrypto:
    def verify_password(self, password_hash: str | None, password: str) -> bool:
        try:
            return password_hasher.verify(password_hash or _DUMMY_HASH, password)
        except VerificationError:
            return False

    new_refresh = staticmethod(new_refresh)
    refresh_identity = staticmethod(refresh_identity)
    sign_access = staticmethod(sign_access)
