"""Password hashing + JWT encode/decode (P4-M2 · TRD §02.2, Doc05 §05.6).

Pure functions, no DB access — fully unit-testable without a session.
bcrypt cost and the JWT secret/TTLs come from ``AuthSettings`` (never
hardcoded, never logged). Access tokens carry ``sub`` (user id) and
``role`` per TRD §02.6's own auth summary; refresh tokens are opaque random
strings (NOT JWTs) whose SHA-256 hash is what ``refresh_tokens.token_hash``
stores — matching Doc05's "rotating" column, not a re-derivation of a JWT.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import AuthSettings

_ALGORITHM = "HS256"


class TokenError(Exception):
    """Raised for any invalid/expired/malformed access token."""


class AccessTokenType(str, Enum):
    access = "access"


@dataclass(frozen=True)
class AccessTokenClaims:
    sub: str
    role: str


def _pwd_context(settings: AuthSettings) -> CryptContext:
    return CryptContext(schemes=["bcrypt"], bcrypt__rounds=settings.password_bcrypt_rounds)


def hash_password(password: str, settings: AuthSettings) -> str:
    return _pwd_context(settings).hash(password)


def verify_password(password: str, password_hash: str, settings: AuthSettings) -> bool:
    return _pwd_context(settings).verify(password, password_hash)


def create_access_token(user_id: str, role: str, settings: AuthSettings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": AccessTokenType.access.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_min),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str, settings: AuthSettings) -> AccessTokenClaims:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise TokenError("invalid or expired access token") from exc
    if payload.get("type") != AccessTokenType.access.value:
        raise TokenError("wrong token type")
    sub = payload.get("sub")
    role = payload.get("role")
    if not sub or not role:
        raise TokenError("malformed token claims")
    return AccessTokenClaims(sub=sub, role=role)


def generate_refresh_token() -> str:
    """Opaque, high-entropy — the raw value handed to the client once."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
