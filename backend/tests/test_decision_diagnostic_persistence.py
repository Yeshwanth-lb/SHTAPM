"""DecisionDiagnosticPersistence sink tests (SQLite, no MQTT/broker) --
mirrors test_telemetry_persistence.py's own pattern."""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Decision, Device  # noqa: E402
from app.schemas.contracts import Attribution, TrustScores  # noqa: E402
from app.schemas.decision_diagnostic import (  # noqa: E402
    ChannelAttribution,
    DecisionDiagnosticMessage,
)
from app.services.decision_diagnostic_persistence import DecisionDiagnosticPersistence  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_NONE_ATTRIBUTION = {
    ch: ChannelAttribution(attribution=Attribution.none, reason="")
    for ch in ("temperature", "vibration", "pressure", "humidity", "gas", "current")
}


def _message(
    device_id="pump-01", ts="2026-09-06T12:00:00.000Z", sample_seq=0, flag=False, severity=0.0
) -> DecisionDiagnosticMessage:
    return DecisionDiagnosticMessage(
        device_id=device_id,
        ts=ts,
        sample_seq=sample_seq,
        window_start_index=0,
        window_end_index=30,
        anomaly_flag=flag,
        anomaly_severity=severity,
        trust=TrustScores(
            temperature=0.9, vibration=0.5, pressure=0.9, humidity=0.9, gas=0.9, current=0.9
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


@pytest.fixture()
def persistence(session_factory) -> DecisionDiagnosticPersistence:
    return DecisionDiagnosticPersistence(session_factory)


def test_persist_creates_device_and_partial_decision_row(persistence, session_factory):
    persistence.persist(_message(flag=True, severity=0.42))

    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        assert device.name == "pump-01"
        row = db.query(Decision).filter(Decision.device_id == device.id).one()
        assert row.anomaly_flag is True
        assert row.anomaly_severity == 0.42
        assert row.trust_temperature == 0.9
        assert row.trust_vibration == 0.5


def test_unsupported_fields_remain_null(persistence, session_factory):
    persistence.persist(_message())

    with session_factory() as db:
        row = db.query(Decision).one()
        assert row.health_state is None
        assert row.failure_eta is None
        assert row.rl_action is None
        assert row.isolated_channels is None
        assert row.substituted_channels is None
        # Per-channel attribution has no single-value column to map into --
        # deliberately not persisted here (see module docstring).
        assert row.attribution is None
        assert row.reason is None


def test_persist_reuses_device_across_messages(persistence, session_factory):
    persistence.persist(_message(ts="2026-09-06T12:00:00.000Z", sample_seq=0))
    persistence.persist(_message(ts="2026-09-06T12:00:01.000Z", sample_seq=1))

    with session_factory() as db:
        devices = db.query(Device).filter(Device.device_id == "pump-01").all()
        assert len(devices) == 1
        rows = db.query(Decision).filter(Decision.device_id == devices[0].id).all()
        assert len(rows) == 2


def test_persist_second_device_gets_its_own_row(persistence, session_factory):
    persistence.persist(_message(device_id="pump-01"))
    persistence.persist(_message(device_id="pump-02"))

    with session_factory() as db:
        assert db.query(Device).count() == 2
        assert db.query(Decision).count() == 2


def test_persist_duplicate_pk_is_skipped_not_raised(persistence, session_factory):
    message = _message(ts="2026-09-06T12:00:00.000Z", sample_seq=0)
    persistence.persist(message)
    persistence.persist(message)  # exact duplicate PK (device_id, ts) -- must not raise

    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        rows = db.query(Decision).filter(Decision.device_id == device.id).all()
        assert len(rows) == 1
