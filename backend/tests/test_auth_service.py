"""P4-M2 — auth service tests (SQLite session, no HTTP layer)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

sa = pytest.importorskip("sqlalchemy")
jose = pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.core.config import AuthSettings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Base, RefreshToken, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.services.auth_service import (  # noqa: E402
    RefreshTokenInvalid,
    authenticate_user,
    issue_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
)
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


@pytest.fixture()
def settings() -> AuthSettings:
    return AuthSettings(
        jwt_secret_key="unit-test-secret",
        jwt_access_ttl_min=15,
        jwt_refresh_ttl_days=7,
        password_bcrypt_rounds=4,
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def user(db, settings) -> User:
    u = User(
        email="operator@example.com",
        password_hash=hash_password("s3cret!", settings),
        role=UserRole.operator,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_authenticate_user_success(db, user, settings):
    result = authenticate_user(db, "operator@example.com", "s3cret!", settings)
    assert result is not None
    assert result.id == user.id


def test_authenticate_user_wrong_password_returns_none(db, user, settings):
    assert authenticate_user(db, "operator@example.com", "wrong", settings) is None


def test_authenticate_user_unknown_email_returns_none(db, settings):
    assert authenticate_user(db, "nobody@example.com", "whatever", settings) is None


def test_authenticate_user_inactive_returns_none(db, user, settings):
    user.is_active = False
    db.commit()
    assert authenticate_user(db, "operator@example.com", "s3cret!", settings) is None


def test_issue_tokens_creates_refresh_row(db, user, settings):
    tokens = issue_tokens(db, user, settings)
    assert tokens.access_token
    assert tokens.refresh_token
    rows = db.query(RefreshToken).filter(RefreshToken.user_id == user.id).all()
    assert len(rows) == 1
    assert rows[0].revoked is False


def test_rotate_refresh_token_happy_path(db, user, settings):
    first = issue_tokens(db, user, settings)
    second = rotate_refresh_token(db, first.refresh_token, settings)
    assert second.refresh_token != first.refresh_token

    rows = {r.token_hash: r for r in db.query(RefreshToken).filter(RefreshToken.user_id == user.id)}
    assert len(rows) == 2
    revoked_flags = sorted(r.revoked for r in rows.values())
    assert revoked_flags == [False, True]


def test_rotate_unknown_refresh_token_raises(db, settings):
    with pytest.raises(RefreshTokenInvalid):
        rotate_refresh_token(db, "not-a-real-token", settings)


def test_rotate_expired_refresh_token_raises(db, user, settings):
    tokens = issue_tokens(db, user, settings)
    row = db.query(RefreshToken).filter(RefreshToken.user_id == user.id).one()
    row.expires_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    with pytest.raises(RefreshTokenInvalid):
        rotate_refresh_token(db, tokens.refresh_token, settings)


def test_reused_rotated_refresh_token_revokes_all_user_tokens(db, user, settings):
    first = issue_tokens(db, user, settings)
    second = rotate_refresh_token(db, first.refresh_token, settings)  # first is now revoked

    # Reusing the already-rotated-away `first` token must fail AND kill `second` too.
    with pytest.raises(RefreshTokenInvalid):
        rotate_refresh_token(db, first.refresh_token, settings)

    rows = db.query(RefreshToken).filter(RefreshToken.user_id == user.id).all()
    assert all(r.revoked for r in rows)

    # `second` (the "legitimate" descendant) must also now be rejected.
    with pytest.raises(RefreshTokenInvalid):
        rotate_refresh_token(db, second.refresh_token, settings)


def test_revoke_refresh_token_logout(db, user, settings):
    tokens = issue_tokens(db, user, settings)
    revoke_refresh_token(db, tokens.refresh_token, user.id)
    row = db.query(RefreshToken).filter(RefreshToken.user_id == user.id).one()
    assert row.revoked is True


def test_revoke_refresh_token_wrong_owner_is_noop(db, user, settings):
    other = User(email="other@example.com", password_hash="x", role=UserRole.analyst)
    db.add(other)
    db.commit()
    db.refresh(other)

    tokens = issue_tokens(db, user, settings)
    revoke_refresh_token(db, tokens.refresh_token, other.id)  # not the owner
    row = db.query(RefreshToken).filter(RefreshToken.user_id == user.id).one()
    assert row.revoked is False
