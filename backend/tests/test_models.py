"""P4-M1 — ORM model shape/constraint tests (Doc05 §05.2).

Runs against an in-memory SQLite engine (portable types in
``app.models.types``/each model module), NOT the real Alembic migration
(Postgres-only, see ``alembic/env.py``) — this is the agreed P4 test
strategy: hardware/DB-free unit tests here, a separate ``db_integration``-
marked suite for anything that genuinely needs Postgres/TimescaleDB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlalchemy.orm")

from app.models import (  # noqa: E402
    Alert,
    AuditLog,
    Base,
    Decision,
    Device,
    LedgerBlock,
    RefreshToken,
    Sensor,
    SensorReading,
    Threshold,
    User,
)
from app.models.enums import AlertSeverity, AlertType, DeviceStatus, UserRole  # noqa: E402
from app.schemas.contracts import Attribution, Channel, HealthState, RLAction  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _now():
    return datetime.now(UTC)


def test_all_tables_created(session):
    tables = set(Base.metadata.tables.keys())
    assert tables == {
        "users",
        "devices",
        "sensors",
        "sensor_readings",
        "decisions",
        "alerts",
        "ledger_blocks",
        "thresholds",
        "audit_log",
        "refresh_tokens",
    }


def test_user_defaults_and_round_trip(session):
    user = User(email="admin@example.com", password_hash="x", role=UserRole.admin)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.is_active is True
    assert isinstance(user.id, uuid.UUID)
    assert user.created_at is not None


def test_user_email_unique(session):
    session.add(User(email="dup@example.com", password_hash="x", role=UserRole.operator))
    session.commit()
    session.add(User(email="dup@example.com", password_hash="y", role=UserRole.analyst))
    with pytest.raises(IntegrityError):
        session.commit()


def test_device_status_and_health_state_defaults(session):
    device = Device(device_id="pump-01", name="Pump-01")
    session.add(device)
    session.commit()
    session.refresh(device)
    assert device.status == DeviceStatus.offline
    assert device.health_state == HealthState.healthy
    assert device.sample_rate_hz == 1


def test_device_id_unique(session):
    session.add(Device(device_id="pump-01", name="A"))
    session.commit()
    session.add(Device(device_id="pump-01", name="B"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_sensor_channel_unique_per_device(session):
    device = Device(device_id="pump-02", name="Pump-02")
    session.add(device)
    session.commit()
    session.add(Sensor(device_id=device.id, channel=Channel.temperature, part="DS18B20"))
    session.commit()
    session.add(Sensor(device_id=device.id, channel=Channel.temperature, part="dup"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_sensor_reading_composite_pk(session):
    device = Device(device_id="pump-03", name="Pump-03")
    session.add(device)
    session.commit()
    reading = SensorReading(
        device_id=device.id,
        ts=_now(),
        sample_seq=1,
        temperature=26.0,
        vibration=0.03,
        pressure=1013.0,
        humidity=45.0,
        gas=150.0,
        current=0.0,
        healthy_mask=0b111111,
    )
    session.add(reading)
    session.commit()
    fetched = session.get(SensorReading, (device.id, reading.ts, 1))
    assert fetched is not None
    assert fetched.temperature == 26.0


def test_decision_optional_fields_and_json_lists(session):
    device = Device(device_id="pump-04", name="Pump-04")
    session.add(device)
    session.commit()
    decision = Decision(
        device_id=device.id,
        ts=_now(),
        anomaly_flag=True,
        anomaly_severity=0.82,
        attribution=Attribution.attack,
        health_state=HealthState.warning,
        failure_eta=142.0,
        rl_action=RLAction.isolate,
        isolated_channels=["pressure"],
        substituted_channels=["pressure"],
    )
    session.add(decision)
    session.commit()
    fetched = session.get(Decision, (device.id, decision.ts))
    assert fetched.isolated_channels == ["pressure"]
    assert fetched.attribution == Attribution.attack


def test_alert_and_ack_fields(session):
    device = Device(device_id="pump-05", name="Pump-05")
    user = User(email="ops@example.com", password_hash="x", role=UserRole.operator)
    session.add_all([device, user])
    session.commit()
    alert = Alert(
        device_id=device.id,
        ts=_now(),
        severity=AlertSeverity.critical,
        type=AlertType.attack,
        message="pressure spoof suspected",
    )
    session.add(alert)
    session.commit()
    assert alert.acknowledged_at is None
    alert.acknowledged_by = user.id
    alert.acknowledged_at = _now()
    session.commit()


def test_ledger_block_unique_index_per_device(session):
    device = Device(device_id="pump-06", name="Pump-06")
    session.add(device)
    session.commit()
    common = dict(
        device_id=device.id,
        ts=_now(),
        event_type="isolate",
        payload={"channel": "pressure"},
        payload_hash="a" * 64,
        prev_hash="0" * 64,
        this_hash="b" * 64,
    )
    session.add(LedgerBlock(block_index=0, **common))
    session.commit()
    session.add(LedgerBlock(block_index=0, **common))
    with pytest.raises(IntegrityError):
        session.commit()


def test_threshold_defaults_and_no_baked_divergence(session):
    device = Device(device_id="pump-07", name="Pump-07")
    session.add(device)
    session.commit()
    threshold = Threshold(device_id=device.id)
    session.add(threshold)
    session.commit()
    session.refresh(threshold)
    assert threshold.trust_trusted_min == 0.7
    assert threshold.trust_malicious_max == 0.4
    assert threshold.substitution_max_seconds == 60
    assert threshold.divergence_threshold is None  # U05 — never silently defaulted


def test_audit_log_and_refresh_token_round_trip(session):
    user = User(email="audit@example.com", password_hash="x", role=UserRole.admin)
    session.add(user)
    session.commit()
    session.add(AuditLog(user_id=user.id, action="config_update", target="thresholds"))
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash="hash",
            expires_at=_now(),
        )
    )
    session.commit()
    assert session.query(AuditLog).count() == 1
    token = session.query(RefreshToken).one()
    assert token.revoked is False
