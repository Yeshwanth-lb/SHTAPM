"""P4-M5 — /api/ledger HTTP-layer tests + threshold-PATCH → ledger wiring."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.api.auth import router as auth_router  # noqa: E402
from app.api.deps import get_auth_settings  # noqa: E402
from app.api.devices import router as devices_router  # noqa: E402
from app.api.ledger import router as ledger_router  # noqa: E402
from app.core.config import AuthSettings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Base, Device, LedgerBlock, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.services import ledger as ledger_service  # noqa: E402
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
    for router in (auth_router, devices_router, ledger_router):
        app.include_router(router)

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_settings] = lambda: TEST_SETTINGS
    return TestClient(app)


@pytest.fixture()
def seed(session_factory):
    """admin, analyst (owns pump-01), operator (owns nothing); pump-02 unowned."""
    with session_factory() as db:
        admin = User(
            email="admin@example.com",
            password_hash=hash_password("adminpw", TEST_SETTINGS),
            role=UserRole.admin,
        )
        analyst = User(
            email="analyst@example.com",
            password_hash=hash_password("anpw", TEST_SETTINGS),
            role=UserRole.analyst,
        )
        operator = User(
            email="operator@example.com",
            password_hash=hash_password("oppw", TEST_SETTINGS),
            role=UserRole.operator,
        )
        db.add_all([admin, analyst, operator])
        db.commit()
        db.refresh(analyst)

        pump01 = Device(device_id="pump-01", name="Pump 01", owner_user_id=analyst.id)
        pump02 = Device(device_id="pump-02", name="Pump 02")
        db.add_all([pump01, pump02])
        db.commit()
        db.refresh(pump01)

        ledger_service.append(db, device_id=pump01.id, event_type="isolate", payload={"c": "p"})
        ledger_service.append(db, device_id=pump01.id, event_type="safe_stop", payload={})


def _login(client, email, password) -> str:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_analyst_lists_own_device_ledger(client, seed):
    token = _login(client, "analyst@example.com", "anpw")
    r = client.get("/api/ledger/pump-01", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["block_index"] == 0
    assert body[1]["block_index"] == 1


def test_operator_cannot_read_ledger(client, seed):
    token = _login(client, "operator@example.com", "oppw")
    r = client.get("/api/ledger/pump-01", headers=_auth(token))
    assert r.status_code == 403


def test_analyst_cannot_read_unowned_device_ledger(client, seed):
    token = _login(client, "analyst@example.com", "anpw")
    r = client.get("/api/ledger/pump-02", headers=_auth(token))
    assert r.status_code == 404


def test_admin_verify_valid_chain(client, seed):
    token = _login(client, "admin@example.com", "adminpw")
    r = client.post("/api/ledger/pump-01/verify", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == {"valid": True, "broken_at": None}


def test_admin_verify_detects_tamper(client, seed, session_factory):
    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        block = (
            db.query(LedgerBlock)
            .filter(LedgerBlock.device_id == device.id, LedgerBlock.block_index == 0)
            .one()
        )
        block.payload = {"tampered": True}
        db.commit()

    token = _login(client, "admin@example.com", "adminpw")
    r = client.post("/api/ledger/pump-01/verify", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == {"valid": False, "broken_at": 0}


def test_export_json_default(client, seed):
    token = _login(client, "admin@example.com", "adminpw")
    r = client.get("/api/ledger/pump-01/export", headers=_auth(token))
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_export_csv(client, seed):
    token = _login(client, "admin@example.com", "adminpw")
    r = client.get(
        "/api/ledger/pump-01/export", params={"format": "csv"}, headers=_auth(token)
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "block_index" in r.text
    assert "isolate" in r.text


def test_export_invalid_format_is_400(client, seed):
    token = _login(client, "admin@example.com", "adminpw")
    r = client.get(
        "/api/ledger/pump-01/export", params={"format": "xml"}, headers=_auth(token)
    )
    assert r.status_code == 400


def test_threshold_patch_writes_ledger_block(client, seed):
    token = _login(client, "admin@example.com", "adminpw")
    r = client.patch(
        "/api/devices/pump-01/thresholds",
        json={"divergence_threshold": 3.1},
        headers=_auth(token),
    )
    assert r.status_code == 200

    ledger = client.get("/api/ledger/pump-01", headers=_auth(token)).json()
    assert len(ledger) == 3  # 2 seeded + 1 from this PATCH
    newest = ledger[-1]
    assert newest["event_type"] == "config_update"
    assert newest["payload"]["changed"] == {"divergence_threshold": 3.1}


def test_threshold_patch_with_no_changes_does_not_write_ledger_block(client, seed):
    token = _login(client, "admin@example.com", "adminpw")
    client.patch("/api/devices/pump-01/thresholds", json={}, headers=_auth(token))

    ledger = client.get("/api/ledger/pump-01", headers=_auth(token)).json()
    assert len(ledger) == 2  # unchanged — no-op PATCH must not pollute the chain
