"""P4-M2 — pure password/JWT helper tests (no DB, no app)."""

from __future__ import annotations

import time

import pytest

jose = pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.core.config import AuthSettings  # noqa: E402
from app.core.security import (  # noqa: E402
    TokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


@pytest.fixture()
def settings() -> AuthSettings:
    return AuthSettings(
        jwt_secret_key="unit-test-secret-not-real",
        jwt_access_ttl_min=15,
        jwt_refresh_ttl_days=7,
        password_bcrypt_rounds=4,  # cheapest valid cost, fast tests
    )


def test_password_hash_and_verify_round_trip(settings):
    hashed = hash_password("correct horse battery staple", settings)
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed, settings)
    assert not verify_password("wrong password", hashed, settings)


def test_access_token_round_trip(settings):
    token = create_access_token("11111111-1111-1111-1111-111111111111", "admin", settings)
    claims = decode_access_token(token, settings)
    assert claims.sub == "11111111-1111-1111-1111-111111111111"
    assert claims.role == "admin"


def test_access_token_rejects_wrong_secret(settings):
    token = create_access_token("u1", "operator", settings)
    other = AuthSettings(
        jwt_secret_key="a-different-secret",
        jwt_access_ttl_min=15,
        jwt_refresh_ttl_days=7,
        password_bcrypt_rounds=4,
    )
    with pytest.raises(TokenError):
        decode_access_token(token, other)


def test_access_token_expiry_enforced(settings):
    short_lived = AuthSettings(
        jwt_secret_key=settings.jwt_secret_key,
        jwt_access_ttl_min=0,  # expires immediately
        jwt_refresh_ttl_days=7,
        password_bcrypt_rounds=4,
    )
    token = create_access_token("u1", "operator", short_lived)
    time.sleep(1.1)
    with pytest.raises(TokenError):
        decode_access_token(token, short_lived)


def test_refresh_token_is_opaque_and_hash_is_deterministic():
    raw = generate_refresh_token()
    assert len(raw) > 20
    assert hash_refresh_token(raw) == hash_refresh_token(raw)
    assert hash_refresh_token(raw) != hash_refresh_token(generate_refresh_token())
