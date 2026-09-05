"""P4-M3 — telemetry persistence sink tests (SQLite, no MQTT/broker)."""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Device, SensorReading  # noqa: E402
from app.schemas.build import build_telemetry  # noqa: E402
from app.services.telemetry_persistence import (  # noqa: E402
    ALL_CHANNELS_HEALTHY_MASK,
    TelemetryPersistence,
)
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_SENSORS = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.0,
}


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def persistence(session_factory) -> TelemetryPersistence:
    return TelemetryPersistence(session_factory)


def test_persist_creates_device_and_reading(persistence, session_factory):
    msg = build_telemetry("pump-01", "2026-09-05T12:00:00.000Z", _SENSORS, sample_seq=0)
    persistence.persist(msg)

    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        assert device.name == "pump-01"
        reading = db.query(SensorReading).filter(SensorReading.device_id == device.id).one()
        assert reading.temperature == 26.0
        assert reading.sample_seq == 0
        assert reading.healthy_mask == ALL_CHANNELS_HEALTHY_MASK


def test_persist_updates_last_seen_at(persistence, session_factory):
    msg = build_telemetry("pump-01", "2026-09-05T12:00:00.000Z", _SENSORS, sample_seq=0)
    persistence.persist(msg)

    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        assert device.last_seen_at is not None


def test_persist_reuses_device_across_messages(persistence, session_factory):
    persistence.persist(build_telemetry("pump-01", "2026-09-05T12:00:00.000Z", _SENSORS, 0))
    persistence.persist(build_telemetry("pump-01", "2026-09-05T12:00:01.000Z", _SENSORS, 1))

    with session_factory() as db:
        devices = db.query(Device).filter(Device.device_id == "pump-01").all()
        assert len(devices) == 1
        readings = db.query(SensorReading).filter(SensorReading.device_id == devices[0].id).all()
        assert len(readings) == 2


def test_persist_second_device_gets_its_own_row(persistence, session_factory):
    persistence.persist(build_telemetry("pump-01", "2026-09-05T12:00:00.000Z", _SENSORS, 0))
    persistence.persist(build_telemetry("pump-02", "2026-09-05T12:00:00.000Z", _SENSORS, 0))

    with session_factory() as db:
        assert db.query(Device).count() == 2


def test_persist_duplicate_sample_is_skipped_not_raised(persistence, session_factory):
    msg = build_telemetry("pump-01", "2026-09-05T12:00:00.000Z", _SENSORS, sample_seq=0)
    persistence.persist(msg)
    persistence.persist(msg)  # exact duplicate PK (device_id, ts, sample_seq) — must not raise

    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        readings = db.query(SensorReading).filter(SensorReading.device_id == device.id).all()
        assert len(readings) == 1
