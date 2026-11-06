"""Password hashing for Office Hub sign-in (bcrypt via the maintained ``bcrypt`` package).

passlib 1.7.4 is pinned in requirements but is incompatible with bcrypt>=4.1's
72-byte enforcement, so the ``bcrypt`` library is used directly. No custom
crypto: hashes are standard ``$2b$`` strings with a per-hash random salt.
"""
from __future__ import annotations

import bcrypt

BCRYPT_ROUNDS = 12
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 72  # bcrypt's input limit; longer secrets are rejected, never truncated.

_dummy_hash: bytes | None = None


class PasswordPolicyError(ValueError):
    pass


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    if password.strip() != password:
        raise PasswordPolicyError("Password must not start or end with whitespace")


def hash_password(password: str) -> str:
    validate_new_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def _dummy() -> bytes:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = bcrypt.hashpw(b"office-hub-dummy-password", bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return _dummy_hash


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-work check: unknown users / missing hashes still pay one bcrypt verify."""
    candidate = password.encode("utf-8")
    if len(candidate) > MAX_PASSWORD_BYTES:
        candidate = candidate[:MAX_PASSWORD_BYTES]
        too_long = True
    else:
        too_long = False
    if not password_hash:
        bcrypt.checkpw(candidate, _dummy())
        return False
    try:
        ok = bcrypt.checkpw(candidate, password_hash.encode("ascii"))
    except ValueError:
        bcrypt.checkpw(candidate, _dummy())
        return False
    return ok and not too_long
