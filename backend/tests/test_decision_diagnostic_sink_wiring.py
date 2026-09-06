"""Proves DecisionDiagnosticPersistence wires into
DecisionDiagnosticConsumer.add_sink() exactly like TelemetryPersistence
does into TelemetryConsumer, with no change to the consumer itself, and
that the two consumers/sinks are fully independent of each other."""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Decision, Device, SensorReading  # noqa: E402
from app.mqtt.consumer import TelemetryConsumer  # noqa: E402
from app.mqtt.decision_diagnostic_consumer import DecisionDiagnosticConsumer  # noqa: E402
from app.schemas.contracts import Attribution, TrustScores  # noqa: E402
from app.schemas.decision_diagnostic import (  # noqa: E402
    ChannelAttribution,
    DecisionDiagnosticMessage,
)
from app.services.decision_diagnostic_persistence import DecisionDiagnosticPersistence  # noqa: E402
from app.services.telemetry_persistence import TelemetryPersistence  # noqa: E402
from app.services.telemetry_store import TelemetryStore  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_NONE_ATTRIBUTION = {
    ch: ChannelAttribution(attribution=Attribution.none, reason="")
    for ch in ("temperature", "vibration", "pressure", "humidity", "gas", "current")
}


class FakeMsg:
    def __init__(self, topic: str, payload):
        self.topic = topic
        self.payload = payload


def _telemetry_payload(device_id="pump-01", seq=0) -> str:
    return (
        '{"device_id":"%s","ts":"2026-09-06T12:00:00.000Z",'
        '"sensors":{"temperature":26.0,"vibration":0.03,"pressure":1013.0,'
        '"humidity":45.0,"gas":150.0,"current":0.42},"sample_seq":%d}' % (device_id, seq)
    )


def _decision_diagnostic_message() -> DecisionDiagnosticMessage:
    return DecisionDiagnosticMessage(
        device_id="pump-01",
        ts="2026-09-06T12:00:00.000Z",
        sample_seq=0,
        window_start_index=0,
        window_end_index=30,
        anomaly_flag=False,
        anomaly_severity=0.0,
        trust=TrustScores(
            temperature=0.9, vibration=0.9, pressure=0.9, humidity=0.9, gas=0.9, current=0.9
        ),
        attribution=_NONE_ATTRIBUTION,
        isolation_candidates=[],
        tracked_isolation_candidates=[],
    )


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_decision_diagnostic_sink_receives_validated_messages_only(session_factory):
    consumer = DecisionDiagnosticConsumer()
    persistence = DecisionDiagnosticPersistence(session_factory)
    consumer.add_sink(persistence.persist)

    consumer.handle(
        FakeMsg(
            "shtapm/pump-01/decision_diagnostic",
            _decision_diagnostic_message().model_dump_json().encode(),
        )
    )

    with session_factory() as db:
        assert db.query(Device).filter(Device.device_id == "pump-01").count() == 1
        assert db.query(Decision).count() == 1


def test_decision_diagnostic_sink_never_sees_rejected_messages(session_factory):
    consumer = DecisionDiagnosticConsumer()
    persistence = DecisionDiagnosticPersistence(session_factory)
    consumer.add_sink(persistence.persist)

    consumer.handle(FakeMsg("shtapm/pump-01/decision_diagnostic", b"not-json{"))

    with session_factory() as db:
        assert db.query(Device).count() == 0
        assert db.query(Decision).count() == 0


def test_broken_decision_diagnostic_sink_does_not_break_ingestion(session_factory):
    consumer = DecisionDiagnosticConsumer()

    def _broken_sink(message):
        raise RuntimeError("db is on fire")

    received = []
    consumer.add_sink(_broken_sink)
    consumer.add_sink(received.append)

    consumer.handle(
        FakeMsg(
            "shtapm/pump-01/decision_diagnostic",
            _decision_diagnostic_message().model_dump_json().encode(),
        )
    )
    assert len(received) == 1


def test_telemetry_and_decision_diagnostic_consumers_are_fully_independent(session_factory):
    """A malformed/failing message on one topic's consumer must never touch
    the other's store/table -- they are separate objects with separate
    subscriptions, never sharing state."""
    telemetry_store = TelemetryStore()
    telemetry_consumer = TelemetryConsumer(telemetry_store)
    telemetry_persistence = TelemetryPersistence(session_factory)
    telemetry_consumer.add_sink(telemetry_persistence.persist)

    decision_consumer = DecisionDiagnosticConsumer()
    decision_persistence = DecisionDiagnosticPersistence(session_factory)
    decision_consumer.add_sink(decision_persistence.persist)

    # Break the decision_diagnostic topic entirely (malformed payload) --
    # telemetry ingestion must be completely unaffected.
    decision_consumer.handle(FakeMsg("shtapm/pump-01/decision_diagnostic", b"garbage"))
    telemetry_consumer.handle(
        FakeMsg("shtapm/pump-01/telemetry", _telemetry_payload().encode())
    )

    assert decision_consumer.error_count == 1
    assert telemetry_consumer.error_count == 0
    assert telemetry_store.count == 1
    with session_factory() as db:
        assert db.query(SensorReading).count() == 1
        assert db.query(Decision).count() == 0

    # And the reverse: breaking telemetry must never affect decision_diagnostic.
    telemetry_consumer.handle(FakeMsg("shtapm/pump-01/telemetry", b"garbage"))
    decision_consumer.handle(
        FakeMsg(
            "shtapm/pump-01/decision_diagnostic",
            _decision_diagnostic_message().model_dump_json().encode(),
        )
    )
    assert telemetry_consumer.error_count == 1
    assert decision_consumer.error_count == 1  # unchanged from before this second block
    with session_factory() as db:
        assert db.query(SensorReading).count() == 1  # unaffected by the garbage telemetry msg
        assert db.query(Decision).count() == 1
