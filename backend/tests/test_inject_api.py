"""Scenario injection (D032): command contract, REST endpoints, RBAC, audit,
ledger, and honest delivery reporting -- SQLite + fake MQTT client."""

from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.api.auth import router as auth_router  # noqa: E402
from app.api.deps import get_auth_settings  # noqa: E402
from app.api.inject import InjectionRegistry  # noqa: E402
from app.api.inject import router as inject_router  # noqa: E402
from app.core.config import AuthSettings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import AuditLog, Base, Device, LedgerBlock, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.mqtt.command_publisher import CommandPublisher  # noqa: E402
from app.schemas.command import (  # noqa: E402
    MAX_DURATION_S,
    SCENARIO_PARAMS,
    CancelCommand,
    InjectCommand,
    parse_command,
)
from app.services import ledger as ledger_service  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

TEST_SETTINGS = AuthSettings(
    jwt_secret_key="unit-test-secret",
    jwt_access_ttl_min=15,
    jwt_refresh_ttl_days=7,
    password_bcrypt_rounds=4,
)

_EXAMPLE_PARAMS = {
    "drift": {"rate": 0.01},
    "spike": {"amplitude": 2.0},
    "stuck_at": {},
    "bias_fdi": {"bias": 0.3},
    "ramp_fdi": {"slope": 0.02},
    "replay": {"lookback_s": 120},
    "constant_spoof": {"value": 0.8},
    "adaptive_stealth_fdi": {"rate": 0.05, "residual_cap": 0.2},
}


def _command(**overrides) -> dict:
    base = {
        "action": "inject",
        "command_id": "c1",
        "device_id": "pump-01",
        "scenario": "constant_spoof",
        "channel": "current",
        "duration_s": 60,
        "params": {"value": 0.8},
        "issued_by": "admin@example.com",
        "issued_at": "2026-10-26T10:00:00.000+00:00",
    }
    base.update(overrides)
    return base


# --- contract -------------------------------------------------------------------


@pytest.mark.parametrize("scenario", sorted(SCENARIO_PARAMS))
def test_every_scenario_accepts_its_documented_params(scenario):
    command = InjectCommand(
        **_command(scenario=scenario, params=_EXAMPLE_PARAMS[scenario], duration_s=60)
    )
    assert command.kind == ("fault" if scenario in {"drift", "spike", "stuck_at"} else "attack")


def test_missing_and_unknown_params_are_rejected():
    with pytest.raises(ValidationError, match="requires params"):
        InjectCommand(**_command(params={}))
    with pytest.raises(ValidationError, match="does not accept"):
        InjectCommand(**_command(params={"value": 1.0, "bias": 2.0}))


def test_non_finite_params_are_rejected():
    with pytest.raises(ValidationError):
        InjectCommand(**_command(params={"value": float("nan")}))


def test_duration_is_bounded():
    with pytest.raises(ValidationError):
        InjectCommand(**_command(duration_s=0))
    with pytest.raises(ValidationError):
        InjectCommand(**_command(duration_s=MAX_DURATION_S + 1))


def test_replay_lookback_must_not_overlap_and_must_be_whole_seconds():
    with pytest.raises(ValidationError, match="lookback_s must be >= duration_s"):
        InjectCommand(**_command(scenario="replay", params={"lookback_s": 30}, duration_s=60))
    with pytest.raises(ValidationError, match="whole number"):
        InjectCommand(**_command(scenario="replay", params={"lookback_s": 90.5}, duration_s=60))


def test_stealth_residual_cap_must_be_positive():
    with pytest.raises(ValidationError, match="residual_cap"):
        InjectCommand(
            **_command(scenario="adaptive_stealth_fdi", params={"rate": 0.1, "residual_cap": 0})
        )


def test_stuck_at_accepts_an_optional_held_value():
    command = InjectCommand(**_command(scenario="stuck_at", params={"held_value": 1.5}))
    assert command.params == {"held_value": 1.5}


def test_parse_command_discriminates_and_forbids_extra_fields():
    assert isinstance(parse_command(json.dumps(_command())), InjectCommand)
    cancel = parse_command(
        json.dumps(
            {
                "action": "cancel",
                "command_id": "*",
                "device_id": "pump-01",
                "issued_by": "a",
                "issued_at": "t",
            }
        )
    )
    assert isinstance(cancel, CancelCommand)
    with pytest.raises(ValidationError):
        parse_command(json.dumps({**_command(), "relay": "off"}))
    with pytest.raises(ValidationError):
        parse_command(json.dumps({**_command(), "action": "actuate"}))


# --- REST ---------------------------------------------------------------------------


class _FakeInfo:
    def __init__(self, rc: int) -> None:
        self.rc = rc


class _FakeMqtt:
    def __init__(self) -> None:
        self.connected = True
        self.rc = 0
        self.published: list[tuple[str, str, int]] = []

    def is_connected(self) -> bool:
        return self.connected

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return _FakeInfo(self.rc)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def mqtt() -> _FakeMqtt:
    return _FakeMqtt()


@pytest.fixture()
def client(session_factory, mqtt):
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(inject_router)
    publisher = CommandPublisher()
    publisher.attach(mqtt)
    app.state.command_publisher = publisher
    app.state.injection_registry = InjectionRegistry()

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_settings] = lambda: TEST_SETTINGS
    return TestClient(app)


@pytest.fixture()
def seed(session_factory):
    """admin; analyst owns pump-01; operator owns nothing; pump-02 unowned."""
    with session_factory() as db:
        users = {
            role: User(
                email=f"{role.value}@example.com",
                password_hash=hash_password("pw", TEST_SETTINGS),
                role=role,
            )
            for role in UserRole
        }
        db.add_all(users.values())
        db.commit()
        analyst = users[UserRole.analyst]
        db.refresh(analyst)
        db.add_all(
            [
                Device(device_id="pump-01", name="Pump 01", owner_user_id=analyst.id),
                Device(device_id="pump-02", name="Pump 02"),
            ]
        )
        db.commit()


def _auth(client, role: str) -> dict:
    r = client.post("/api/auth/login", json={"email": f"{role}@example.com", "password": "pw"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_SPOOF = {
    "scenario": "constant_spoof",
    "channel": "current",
    "duration_s": 45,
    "params": {"value": 0.8},
}


def _ledger(session_factory, device_id: str) -> list[LedgerBlock]:
    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == device_id).one()
        return (
            db.query(LedgerBlock)
            .filter(LedgerBlock.device_id == device.id)
            .order_by(LedgerBlock.block_index)
            .all()
        )


def _audit(session_factory, action: str) -> list[AuditLog]:
    with session_factory() as db:
        return db.query(AuditLog).filter(AuditLog.action == action).all()


def test_admin_injection_is_published_audited_and_chained(client, seed, mqtt, session_factory):
    r = client.post("/api/devices/pump-02/inject", json=_SPOOF, headers=_auth(client, "admin"))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["kind"] == "attack" and body["active"] is True
    assert body["issued_by"] == "admin@example.com"

    topic, payload, qos = mqtt.published[-1]
    assert topic == "shtapm/pump-02/command" and qos == 1
    sent = parse_command(payload)
    assert isinstance(sent, InjectCommand)
    assert sent.command_id == body["command_id"]
    assert sent.params == {"value": 0.8}

    [entry] = _audit(session_factory, "scenario_inject")
    assert entry.detail["sent"] is True
    blocks = _ledger(session_factory, "pump-02")
    assert [b.event_type for b in blocks] == ["scenario_inject"]
    assert blocks[0].payload["command_id"] == body["command_id"]
    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-02").one()
        assert ledger_service.verify(db, device.id).valid is True


def test_analyst_can_inject_on_an_owned_device(client, seed):
    r = client.post("/api/devices/pump-01/inject", json=_SPOOF, headers=_auth(client, "analyst"))
    assert r.status_code == 202


def test_analyst_cannot_inject_on_a_device_it_does_not_own(client, seed, mqtt):
    r = client.post("/api/devices/pump-02/inject", json=_SPOOF, headers=_auth(client, "analyst"))
    assert r.status_code == 404
    assert mqtt.published == []


def test_operator_is_forbidden_and_the_denial_is_audited(client, seed, mqtt, session_factory):
    r = client.post("/api/devices/pump-01/inject", json=_SPOOF, headers=_auth(client, "operator"))
    assert r.status_code == 403
    assert mqtt.published == []
    assert len(_audit(session_factory, "rbac_denied")) == 1


def test_unauthenticated_inject_is_rejected(client, seed, mqtt):
    assert client.post("/api/devices/pump-01/inject", json=_SPOOF).status_code == 401
    assert mqtt.published == []


def test_invalid_params_are_422_and_nothing_is_sent(client, seed, mqtt):
    bad = {**_SPOOF, "params": {}}
    r = client.post("/api/devices/pump-02/inject", json=bad, headers=_auth(client, "admin"))
    assert r.status_code == 422
    assert mqtt.published == []


def test_broker_down_is_reported_as_503_audited_but_not_chained(
    client, seed, mqtt, session_factory
):
    mqtt.connected = False
    r = client.post("/api/devices/pump-02/inject", json=_SPOOF, headers=_auth(client, "admin"))
    assert r.status_code == 503
    [entry] = _audit(session_factory, "scenario_inject")
    assert entry.detail["sent"] is False
    assert _ledger(session_factory, "pump-02") == []


def test_client_refusal_is_also_503(client, seed, mqtt):
    mqtt.rc = 4  # MQTT_ERR_NO_CONN
    r = client.post("/api/devices/pump-02/inject", json=_SPOOF, headers=_auth(client, "admin"))
    assert r.status_code == 503


def test_get_reports_the_active_injection_then_cancel_clears_it(
    client, seed, mqtt, session_factory
):
    headers = _auth(client, "admin")
    assert client.get("/api/devices/pump-02/inject", headers=headers).json() is None
    issued = client.post("/api/devices/pump-02/inject", json=_SPOOF, headers=headers).json()

    current = client.get("/api/devices/pump-02/inject", headers=headers).json()
    assert current["command_id"] == issued["command_id"] and current["active"] is True

    r = client.post("/api/devices/pump-02/inject/cancel", headers=headers)
    assert r.status_code == 200 and r.json()["command_id"] == issued["command_id"]
    cancel = parse_command(mqtt.published[-1][1])
    assert isinstance(cancel, CancelCommand) and cancel.command_id == issued["command_id"]
    assert client.get("/api/devices/pump-02/inject", headers=headers).json() is None
    assert [b.event_type for b in _ledger(session_factory, "pump-02")] == [
        "scenario_inject",
        "scenario_cancel",
    ]


def test_cancel_without_a_known_injection_cancels_whatever_is_running(client, seed, mqtt):
    r = client.post("/api/devices/pump-02/inject/cancel", headers=_auth(client, "admin"))
    assert r.status_code == 200 and r.json()["command_id"] == "*"
    assert parse_command(mqtt.published[-1][1]).command_id == "*"


def test_operator_can_see_but_not_cancel(client, seed, session_factory):
    with session_factory() as db:
        operator = db.query(User).filter(User.role == UserRole.operator).one()
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        device.owner_user_id = operator.id
        db.commit()
    headers = _auth(client, "operator")
    assert client.get("/api/devices/pump-01/inject", headers=headers).status_code == 200
    assert client.post("/api/devices/pump-01/inject/cancel", headers=headers).status_code == 403


def test_registry_marks_expired_injections_inactive():
    from datetime import UTC, datetime, timedelta

    from app.api.inject import InjectionOut

    now = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
    registry = InjectionRegistry()
    registry.set(
        InjectionOut(
            command_id="c",
            device_id="pump-01",
            scenario="spike",
            kind="fault",
            channel="current",
            duration_s=10,
            params={"amplitude": 1.0},
            issued_by="a",
            issued_at=now,
            expires_at=now + timedelta(seconds=10),
            active=True,
        )
    )
    assert registry.get("pump-01", now + timedelta(seconds=5)).active is True
    assert registry.get("pump-01", now + timedelta(seconds=11)).active is False
