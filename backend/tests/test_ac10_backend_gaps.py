"""AC10 gap-fill: Doc06 Happy/Edge/Sad rows that had no direct test.

Each test names the Doc06 row it covers. Same standalone-app isolation
pattern as ``test_rest_api.py`` (routers + overridden ``get_db``/auth
settings, no MQTT lifespan). Fixtures are duplicated rather than imported
because ``--import-mode=importlib`` makes sibling test modules awkward to
import. See ``project-state/AC10_TEST_COVERAGE.md``.
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.api.alerts import router as alerts_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.deps import get_auth_settings  # noqa: E402
from app.api.devices import router as devices_router  # noqa: E402
from app.api.users import router as users_router  # noqa: E402
from app.core.config import AuthSettings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.security import decode_access_token, hash_password  # noqa: E402
from app.models import AuditLog, Base, Device, LedgerBlock, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.schemas.build import build_telemetry  # noqa: E402
from app.ws.broadcaster import TelemetryBroadcaster  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

TEST_SETTINGS = AuthSettings(
    jwt_secret_key="unit-test-secret",
    jwt_access_ttl_min=15,
    jwt_refresh_ttl_days=7,
    password_bcrypt_rounds=4,
)

SQLI_PAYLOADS = (
    "' OR '1'='1",
    "pump-01'; DROP TABLE users; --",
    '" OR ""="',
    "1 UNION SELECT password_hash FROM users",
)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def client(session_factory):
    app = FastAPI()
    for router in (auth_router, devices_router, alerts_router, users_router):
        app.include_router(router)

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_settings] = lambda: TEST_SETTINGS
    return TestClient(app)


@pytest.fixture()
def seed(session_factory):
    with session_factory() as db:
        admin = User(
            email="admin@example.com",
            password_hash=hash_password("adminpw", TEST_SETTINGS),
            role=UserRole.admin,
        )
        operator = User(
            email="operator@example.com",
            password_hash=hash_password("oppw", TEST_SETTINGS),
            role=UserRole.operator,
        )
        db.add_all([admin, operator])
        db.commit()
        db.refresh(operator)
        db.add(Device(device_id="pump-01", name="Pump 01", owner_user_id=operator.id))
        db.commit()


def _token(client, email, password) -> str:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _rbac_denials(session_factory) -> list[AuditLog]:
    with session_factory() as db:
        return db.query(AuditLog).filter(AuditLog.action == "rbac_denied").all()


# ---- Phase 1 Happy: "Env loads per service — missing var → clear boot error naming it"


def test_missing_jwt_secret_fails_at_boot_naming_the_variable(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        AuthSettings.from_env()


def test_blank_jwt_secret_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        AuthSettings.from_env()


# ---- Phase 2 Happy: "Login valid → access+refresh; role in token"


@pytest.mark.parametrize(
    ("email", "password", "role"),
    [("admin@example.com", "adminpw", "admin"), ("operator@example.com", "oppw", "operator")],
)
def test_login_access_token_carries_the_users_role(client, seed, email, password, role):
    body = client.post("/api/auth/login", json={"email": email, "password": password}).json()
    assert body["refresh_token"]
    assert decode_access_token(body["access_token"], TEST_SETTINGS).role == role


# ---- Phase 2 Sad: "Non-admin writes thresholds → 403 + audit_log entry"


def test_operator_patching_thresholds_is_403_audited_and_changes_nothing(
    client, seed, session_factory
):
    operator = _token(client, "operator@example.com", "oppw")
    r = client.patch(
        "/api/devices/pump-01/thresholds",
        json={"divergence_threshold": 9.9},
        headers=_auth(operator),
    )
    assert r.status_code == 403

    denials = _rbac_denials(session_factory)
    assert len(denials) == 1
    assert denials[0].detail["actual_role"] == "operator"

    admin = _token(client, "admin@example.com", "adminpw")
    current = client.get("/api/devices/pump-01/thresholds", headers=_auth(admin))
    assert current.status_code == 200
    assert current.json()["divergence_threshold"] is None
    with session_factory() as db:
        assert db.query(LedgerBlock).count() == 0


# ---- Phase 4 Sad: "Operator hits admin REST → 403 + audit"


def test_operator_hitting_admin_users_route_is_403_and_audited(client, seed, session_factory):
    operator = _token(client, "operator@example.com", "oppw")
    r = client.get("/api/users", headers=_auth(operator))
    assert r.status_code == 403
    denials = _rbac_denials(session_factory)
    assert len(denials) == 1
    assert denials[0].detail["required_roles"] == ["admin"]


# ---- Phase 2 Sad: "SQLi attempt in params → parameterized; no leak"


@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_sql_injection_in_path_and_query_params_is_inert(client, seed, session_factory, payload):
    admin = _token(client, "admin@example.com", "adminpw")

    r = client.get(f"/api/devices/{quote(payload, safe='')}", headers=_auth(admin))
    assert r.status_code == 404
    assert "password" not in r.text.lower()

    r = client.get(f"/api/devices/{quote(payload, safe='')}/readings", headers=_auth(admin))
    assert r.status_code == 404

    r = client.get("/api/alerts", params={"device": payload}, headers=_auth(admin))
    assert r.status_code == 200
    assert r.json() == []

    with session_factory() as db:
        assert db.query(User).count() == 2
        assert db.query(Device).count() == 1


@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_sql_injection_in_login_email_is_a_plain_401(client, seed, payload):
    r = client.post("/api/auth/login", json={"email": payload, "password": "x"})
    assert r.status_code in (401, 422)
    assert "password_hash" not in r.text


# ---- Phase 4 Edge: "5 concurrent WS clients — all receive"


def test_five_concurrent_ws_subscribers_each_receive_every_frame_in_order():
    async def scenario():
        broadcaster = TelemetryBroadcaster(asyncio.get_running_loop())
        queues = [await broadcaster.subscribe() for _ in range(5)]
        assert broadcaster.client_count == 5

        sensors = {
            "temperature": 26.0,
            "vibration": 0.03,
            "pressure": 1013.0,
            "humidity": 45.0,
            "gas": 150.0,
            "current": 0.42,
        }
        for seq in range(3):
            broadcaster.publish_from_thread(
                build_telemetry("pump-01", "2026-09-24T10:00:00.000Z", sensors, seq)
            )
        await asyncio.sleep(0)

        for q in queues:
            got = [q.get_nowait()["sample_seq"] for _ in range(q.qsize())]
            assert got == [0, 1, 2]

    asyncio.run(scenario())
