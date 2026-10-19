"""Password hashing and opaque tokens.

* Passwords: argon2id (argon2-cffi defaults, which follow the RFC 9106 recommendations).
* Session and CSRF tokens: 256-bit random, URL-safe. Only their SHA-256 is stored, so a
  database leak does not hand out live sessions.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Verified against when the username does not exist, so the response time does not reveal
# whether an account exists.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        msg = f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        raise ValueError(msg)
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verification; ``None`` hash runs against a dummy and returns False."""
    target = password_hash if password_hash is not None else _DUMMY_HASH
    try:
        ok = _hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and password_hash is not None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(presented: str | None, expected_digest: str) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(token_digest(presented), expected_digest)
