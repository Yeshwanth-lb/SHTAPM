"""Pump relay control and status (D041; FR-R1, PRD §18.3 item 3): REST RBAC,
audit, ledger, the actuation consumer and the ledger recorder -- SQLite + fake
MQTT client."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.api.auth import router as auth_router  # noqa: E402
from app.api.deps import get_auth_settings  # noqa: E402
from app.api.relay import router as relay_router  # noqa: E402
from app.core.config import AuthSettings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import AuditLog, Base, Device, LedgerBlock, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.mqtt.actuation_consumer import ActuationConsumer  # noqa: E402
from app.mqtt.command_publisher import CommandPublisher  # noqa: E402
from app.schemas.actuation import ActuationStatus, parse_relay_command  # noqa: E402
from app.schemas.command import CancelCommand  # noqa: E402
from app.services import ledger as ledger_service  # noqa: E402
from app.services.actuation import (  # noqa: E402
    ActuationLedgerRecorder,
    ActuationRegistry,
    event_type_for,
)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

SETTINGS = AuthSettings(
    jwt_secret_key="unit-test-secret",
    jwt_access_ttl_min=15,
    jwt_refresh_ttl_days=7,
    password_bcrypt_rounds=4,
)


class _Info:
    def __init__(self, rc: int) -> None:
        self.rc = rc


class _FakeMqtt:
    def __init__(self) -> None:
        self.connected = True
        self.published: list[tuple[str, str, int]] = []

    def is_connected(self) -> bool:
        return self.connected

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return _Info(0)


def _status(**overrides) -> ActuationStatus:
    values = {
        "device_id": "pump-01",
        "ts": "2026-10-27T10:00:00.000Z",
        "relay": "off",
        "cause": "startup",
        "reason": "edge started; relay forced OFF (safe default)",
        "latched": False,
        "hardware": True,
    }
    values.update(overrides)
    return ActuationStatus(**values)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        users = {
            role: User(
                email=f"{role.value}@example.com",
                password_hash=hash_password("pw", SETTINGS),
                role=role,
            )
            for role in UserRole
        }
        db.add_all(users.values())
        db.commit()
        operator = users[UserRole.operator]
        db.refresh(operator)
        db.add(Device(device_id="pump-01", name="Pump 01", owner_user_id=operator.id))
        db.commit()
    return factory


@pytest.fixture()
def mqtt() -> _FakeMqtt:
    return _FakeMqtt()


@pytest.fixture()
def registry() -> ActuationRegistry:
    return ActuationRegistry()


@pytest.fixture()
def client(session_factory, mqtt, registry):
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(relay_router)
    publisher = CommandPublisher()
    publisher.attach(mqtt)
    app.state.command_publisher = publisher
    app.state.actuation_registry = registry

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_settings] = lambda: SETTINGS
    return TestClient(app)


def _auth(client, role: str) -> dict:
    r = client.post("/api/auth/login", json={"email": f"{role}@example.com", "password": "pw"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _post(client, state: str, role: str = "admin", device: str = "pump-01"):
    return client.post(
        f"/api/devices/{device}/relay", json={"state": state}, headers=_auth(client, role)
    )


def _ledger(session_factory) -> list[LedgerBlock]:
    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        return (
            db.query(LedgerBlock)
            .filter(LedgerBlock.device_id == device.id)
            .order_by(LedgerBlock.block_index)
            .all()
        )


def _audit(session_factory, action: str) -> list[AuditLog]:
    with session_factory() as db:
        return db.query(AuditLog).filter(AuditLog.action == action).all()


# --- POST: start / stop ----------------------------------------------------------


def test_admin_start_is_published_on_the_relay_topic_audited_and_chained(
    client, mqtt, session_factory
):
    r = _post(client, "on")
    assert r.status_code == 202, r.text
    topic, payload, qos = mqtt.published[-1]
    assert topic == "shtapm/pump-01/relay_command" and qos == 1
    command = parse_relay_command(payload)
    assert command.state == "on" and command.issued_by == "admin@example.com"
    [entry] = _audit(session_factory, "relay_command")
    assert entry.detail["sent"] is True
    assert [b.event_type for b in _ledger(session_factory)] == ["relay_command"]


@pytest.mark.parametrize("role", ["operator", "analyst"])
def test_only_admins_switch_the_pump(client, mqtt, session_factory, role):
    r = _post(client, "on", role=role)
    assert r.status_code == 403
    assert mqtt.published == []
    assert len(_audit(session_factory, "rbac_denied")) == 1


def test_unauthenticated_is_401(client, mqtt):
    assert client.post("/api/devices/pump-01/relay", json={"state": "on"}).status_code == 401
    assert mqtt.published == []


def test_invalid_state_is_422(client, mqtt):
    r = client.post(
        "/api/devices/pump-01/relay", json={"state": "maybe"}, headers=_auth(client, "admin")
    )
    assert r.status_code == 422
    assert mqtt.published == []


def test_broker_down_is_503_audited_and_not_chained(client, mqtt, session_factory):
    mqtt.connected = False
    r = _post(client, "off")
    assert r.status_code == 503
    [entry] = _audit(session_factory, "relay_command")
    assert entry.detail["sent"] is False
    assert _ledger(session_factory) == []


def test_unknown_device_is_404(client, mqtt):
    r = _post(client, "on", device="pump-09")
    assert r.status_code == 404
    assert mqtt.published == []


# --- GET: reported state -----------------------------------------------------------


def test_state_is_unknown_until_the_edge_reports(client, registry):
    r = client.get("/api/devices/pump-01/relay", headers=_auth(client, "operator"))
    assert r.status_code == 200
    assert r.json() == {"device_id": "pump-01", "known": False, "status": None}
    registry.update(_status(relay="off", cause="dry_run", latched=True, reason="dry run"))
    body = client.get("/api/devices/pump-01/relay", headers=_auth(client, "operator")).json()
    assert body["known"] is True
    assert body["status"]["cause"] == "dry_run" and body["status"]["latched"] is True


# --- consumer ------------------------------------------------------------------------


def _msg(topic: str, payload) -> SimpleNamespace:
    raw = payload if isinstance(payload, bytes | str) else json.dumps(payload)
    return SimpleNamespace(topic=topic, payload=raw.encode() if isinstance(raw, str) else raw)


def test_consumer_delivers_valid_status_and_rejects_the_rest(registry):
    consumer = ActuationConsumer()
    consumer.add_sink(registry.update)
    consumer.handle(_msg("shtapm/pump-01/actuation", _status().model_dump()))
    assert registry.get("pump-01").cause == "startup"
    consumer.handle(_msg("shtapm/pump-02/actuation", _status().model_dump()))  # mismatch
    consumer.handle(_msg("shtapm/pump-01/actuation", b"garbage"))
    consumer.handle(_msg("shtapm/pump-01/telemetry", _status().model_dump()))
    assert consumer.error_count == 3


# --- ledger recorder --------------------------------------------------------------------


@pytest.mark.parametrize(
    "cause, relay, event",
    [
        ("safe_stop", "off", "safe_stop"),
        ("dry_run", "off", "safe_stop"),
        ("watchdog", "off", "safe_stop"),
        ("command", "on", "relay_on"),
        ("command", "off", "relay_off"),
        ("startup", "off", "relay_off"),
        ("shutdown", "off", "relay_off"),
    ],
)
def test_event_types(cause, relay, event):
    assert event_type_for(_status(cause=cause, relay=relay)) == event


def test_recorder_chains_transitions_once_and_keeps_the_chain_valid(session_factory):
    recorder = ActuationLedgerRecorder(session_factory)
    startup = _status()
    recorder.record(startup)
    recorder.record(startup)  # retained status re-delivered after a reconnect
    recorder.record(_status(ts="2026-10-27T10:01:00.000Z", relay="on", cause="command"))
    recorder.record(
        _status(ts="2026-10-27T10:02:00.000Z", cause="safe_stop", latched=True, reason="x")
    )
    blocks = _ledger(session_factory)
    assert [b.event_type for b in blocks] == ["relay_off", "relay_on", "safe_stop"]
    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        assert ledger_service.verify(db, device.id).valid is True


def test_recorder_ignores_unknown_devices(session_factory):
    ActuationLedgerRecorder(session_factory).record(_status(device_id="pump-77"))
    assert _ledger(session_factory) == []


# --- publisher routing -------------------------------------------------------------------


def test_injection_commands_still_use_the_advisory_topic(mqtt):
    publisher = CommandPublisher()
    publisher.attach(mqtt)
    publisher.publish(
        CancelCommand(
            action="cancel",
            command_id="c1",
            device_id="pump-01",
            issued_by="a@b.c",
            issued_at="2026-10-27T10:00:00.000Z",
        )
    )
    assert mqtt.published[-1][0] == "shtapm/pump-01/command"
