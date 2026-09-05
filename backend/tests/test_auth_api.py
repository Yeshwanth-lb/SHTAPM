"""P4-M2 — /api/auth HTTP-layer tests.

Builds a small standalone FastAPI app (auth router only) with
``get_db``/``get_auth_settings`` overridden to an in-memory SQLite session
and a fixed test secret — deliberately NOT ``app.main.app`` (that lifespan
starts an MQTT consumer and, from later milestones, will require
``DATABASE_URL``/``JWT_SECRET_KEY`` env vars; the auth router itself has no
such dependency and is fully testable in isolation).
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.api.auth import router as auth_router  # noqa: E402
from app.api.deps import get_auth_settings, get_current_user, require_role  # noqa: E402
from app.core.config import AuthSettings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import AuditLog, Base, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from fastapi import APIRouter, Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

TEST_SETTINGS = AuthSettings(
    jwt_secret_key="unit-test-secret",
    jwt_access_ttl_min=15,
    jwt_refresh_ttl_days=7,
    password_bcrypt_rounds=4,
)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def client(session_factory):
    app = FastAPI()
    app.include_router(auth_router)

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_settings] = lambda: TEST_SETTINGS
    return TestClient(app)


@pytest.fixture()
def seeded_user(session_factory) -> str:
    with session_factory() as db:
        user = User(
            email="ops@example.com",
            password_hash=hash_password("s3cret!", TEST_SETTINGS),
            role=UserRole.operator,
        )
        db.add(user)
        db.commit()
    return "ops@example.com"


def test_login_success_returns_tokens(client, seeded_user):
    r = client.post("/api/auth/login", json={"email": seeded_user, "password": "s3cret!"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_wrong_password_is_generic_401(client, seeded_user):
    r = client.post("/api/auth/login", json={"email": seeded_user, "password": "nope"})
    assert r.status_code == 401
    assert "invalid email or password" in r.json()["detail"]


def test_login_unknown_email_is_same_generic_401(client, seeded_user):
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert r.status_code == 401
    assert "invalid email or password" in r.json()["detail"]


def test_refresh_rotates_tokens(client, seeded_user):
    login = client.post("/api/auth/login", json={"email": seeded_user, "password": "s3cret!"})
    old_refresh = login.json()["refresh_token"]

    r = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    assert r.json()["refresh_token"] != old_refresh


def test_refresh_reuse_after_rotation_is_401(client, seeded_user):
    login = client.post("/api/auth/login", json={"email": seeded_user, "password": "s3cret!"})
    old_refresh = login.json()["refresh_token"]
    client.post("/api/auth/refresh", json={"refresh_token": old_refresh})  # rotates it away

    r = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 401


def test_logout_requires_auth(client, seeded_user):
    r = client.post("/api/auth/logout", json={"refresh_token": "whatever"})
    assert r.status_code == 401


def test_logout_revokes_refresh_token(client, seeded_user):
    login = client.post("/api/auth/login", json={"email": seeded_user, "password": "s3cret!"})
    tokens = login.json()

    r = client.post(
        "/api/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 204

    r2 = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401


def test_rbac_denial_is_audited(client, seeded_user, session_factory):
    probe_router = APIRouter()

    @probe_router.get("/probe/admin-only")
    def _probe(user=Depends(require_role(UserRole.admin))):
        return {"ok": True}

    client.app.include_router(probe_router)

    login = client.post("/api/auth/login", json={"email": seeded_user, "password": "s3cret!"})
    access_token = login.json()["access_token"]

    r = client.get("/probe/admin-only", headers={"Authorization": f"Bearer {access_token}"})
    assert r.status_code == 403

    with session_factory() as db:
        entries = db.query(AuditLog).filter(AuditLog.action == "rbac_denied").all()
        assert len(entries) == 1
        assert entries[0].detail["actual_role"] == "operator"
        assert entries[0].detail["required_roles"] == ["admin"]


def test_get_current_user_rejects_missing_token(client, seeded_user):
    probe_router = APIRouter()

    @probe_router.get("/probe/authed")
    def _probe(user=Depends(get_current_user)):
        return {"email": user.email}

    client.app.include_router(probe_router)
    r = client.get("/probe/authed")
    assert r.status_code == 401
