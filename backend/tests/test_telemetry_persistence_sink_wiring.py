"""P4-M3 — proves TelemetryPersistence wires into TelemetryConsumer.add_sink()
exactly like the WS broadcaster does, with no change to the consumer itself."""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Device, SensorReading  # noqa: E402
from app.mqtt.consumer import TelemetryConsumer  # noqa: E402
from app.services.telemetry_persistence import TelemetryPersistence  # noqa: E402
from app.services.telemetry_store import TelemetryStore  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


class FakeMsg:
    def __init__(self, topic: str, payload):
        self.topic = topic
        self.payload = payload


def _valid_payload(device_id="pump-01", seq=0) -> str:
    return (
        '{"device_id":"%s","ts":"2026-09-05T12:00:00.000Z",'
        '"sensors":{"temperature":26.0,"vibration":0.03,"pressure":1013.0,'
        '"humidity":45.0,"gas":150.0,"current":0.42},"sample_seq":%d}' % (device_id, seq)
    )


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_persistence_sink_receives_validated_messages_only(session_factory):
    store = TelemetryStore()
    consumer = TelemetryConsumer(store)
    persistence = TelemetryPersistence(session_factory)
    consumer.add_sink(persistence.persist)

    consumer.handle(FakeMsg("shtapm/pump-01/telemetry", _valid_payload().encode()))

    with session_factory() as db:
        assert db.query(Device).filter(Device.device_id == "pump-01").count() == 1
        assert db.query(SensorReading).count() == 1


def test_persistence_sink_never_sees_rejected_messages(session_factory):
    store = TelemetryStore()
    consumer = TelemetryConsumer(store)
    persistence = TelemetryPersistence(session_factory)
    consumer.add_sink(persistence.persist)

    consumer.handle(FakeMsg("shtapm/pump-01/telemetry", b"not-json{"))

    with session_factory() as db:
        assert db.query(Device).count() == 0
        assert db.query(SensorReading).count() == 0


def test_persistence_sink_failure_does_not_break_ingestion_or_other_sinks(session_factory):
    """Mirrors consumer.handle()'s own contract: 'a sink failure must not
    break ingestion' — a broken persistence sink must not stop the store
    (or a second sink) from receiving the message."""
    store = TelemetryStore()
    consumer = TelemetryConsumer(store)

    def _broken_sink(message):
        raise RuntimeError("db is on fire")

    received = []
    consumer.add_sink(_broken_sink)
    consumer.add_sink(received.append)

    consumer.handle(FakeMsg("shtapm/pump-01/telemetry", _valid_payload().encode()))

    assert store.count == 1
    assert len(received) == 1
