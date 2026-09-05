"""Auth business logic (P4-M2 · Doc05 §05.6/§05.7).

``authenticate_user`` returns ``None`` uniformly for "no such email",
"wrong password", and "inactive user" — the caller must not distinguish
these in the API response (Doc06 P2-AUTH-S1: 401, generic, no user
enumeration).

Refresh-token "family" note: Doc05's ``refresh_tokens`` schema is flat (no
``family_id``/lineage column) — it only has ``token_hash``/``expires_at``/
``revoked`` per user. This module interprets "family" the only way that
flat schema supports: on detected reuse of an already-revoked refresh
token, EVERY refresh token currently issued to that user is revoked
(session-wide), not a narrower per-lineage chain. This is a documented,
schema-compatible interpretation, not a new column/schema change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import AuthSettings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_password,
)
from app.models import RefreshToken, User


class RefreshTokenInvalid(Exception):
    """Unknown, expired, or revoked refresh token (including detected reuse)."""


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def authenticate_user(
    db: Session, email: str, password: str, settings: AuthSettings
) -> User | None:
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash, settings):
        return None
    return user


def issue_tokens(db: Session, user: User, settings: AuthSettings) -> IssuedTokens:
    access = create_access_token(str(user.id), user.role.value, settings)
    raw_refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_ttl_days),
            revoked=False,
        )
    )
    db.commit()
    return IssuedTokens(access_token=access, refresh_token=raw_refresh)


def rotate_refresh_token(
    db: Session, raw_refresh_token: str, settings: AuthSettings
) -> IssuedTokens:
    """Validate + rotate. Raises ``RefreshTokenInvalid`` on any failure,
    including reuse of an already-revoked token (which additionally revokes
    every refresh token belonging to that user — see module docstring)."""
    token_hash = hash_refresh_token(raw_refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).one_or_none()
    if row is None:
        raise RefreshTokenInvalid("unknown refresh token")

    now = datetime.now(UTC)
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)

    if row.revoked:
        # Reuse of a rotated-away token: treat as compromise, kill the whole session set.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == row.user_id)
            .values(revoked=True)
        )
        db.commit()
        raise RefreshTokenInvalid("refresh token reuse detected; all sessions revoked")

    if expires_at < now:
        raise RefreshTokenInvalid("refresh token expired")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise RefreshTokenInvalid("user no longer active")

    row.revoked = True
    db.commit()
    return issue_tokens(db, user, settings)


def revoke_refresh_token(db: Session, raw_refresh_token: str, owner_user_id) -> None:
    """Logout: revoke one token owned by ``owner_user_id``. Unknown tokens and
    tokens owned by a different user are both a no-op (idempotent; never
    reveals whether the token exists / who owns it)."""
    token_hash = hash_refresh_token(raw_refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).one_or_none()
    if row is not None and row.user_id == owner_user_id:
        row.revoked = True
        db.commit()


def record_login(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(UTC)
    db.commit()
