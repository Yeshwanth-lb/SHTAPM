"""Dead sensors on the backend (D045): registry, ledger events, condition."""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Device, LedgerBlock  # noqa: E402
from app.schemas.contracts import Attribution, HealthState, TrustScores  # noqa: E402
from app.schemas.decision_diagnostic import (  # noqa: E402
    ChannelAttribution,
    DecisionDiagnosticMessage,
)
from app.services import ledger as ledger_service  # noqa: E402
from app.services.condition import ConditionRollup  # noqa: E402
from app.services.sensor_health import SensorHealthLedger, SensorHealthRegistry  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

CHANNELS = ("temperature", "vibration", "pressure", "humidity", "gas", "current")


def _decision(stale=(), i=0) -> DecisionDiagnosticMessage:
    clean = ChannelAttribution(attribution=Attribution.none, reason="")
    return DecisionDiagnosticMessage(
        device_id="pump-01",
        ts=f"2026-10-27T10:00:{i:02d}.000Z",
        sample_seq=i,
        window_start_index=0,
        window_end_index=30,
        anomaly_flag=False,
        anomaly_severity=0.1,
        trust=TrustScores(**{ch: 0.9 for ch in CHANNELS}),
        attribution={ch: clean for ch in CHANNELS},
        isolation_candidates=[],
        tracked_isolation_candidates=[],
        stale_channels=list(stale),
    )


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    f = sessionmaker(bind=engine, expire_on_commit=False)
    with f() as db:
        db.add(Device(device_id="pump-01", name="Pump 01"))
        db.commit()
    return f


def test_registry_keeps_when_each_sensor_went_stale():
    registry = SensorHealthRegistry()
    registry.update(_decision(i=0))
    registry.update(_decision(stale=["humidity"], i=1))
    registry.update(_decision(stale=["humidity", "current"], i=2))
    assert registry.get("pump-01") == {
        "humidity": "2026-10-27T10:00:01.000Z",
        "current": "2026-10-27T10:00:02.000Z",
    }
    registry.update(_decision(stale=["current"], i=3))
    assert set(registry.get("pump-01")) == {"current"}


def test_ledger_chains_each_death_and_recovery_once(factory):
    recorder = SensorHealthLedger(factory)
    for i, stale in enumerate([[], ["humidity"], ["humidity"], ["humidity"], []]):
        recorder.record(_decision(stale=stale, i=i))
    with factory() as db:
        device = db.query(Device).one()
        blocks = db.query(LedgerBlock).order_by(LedgerBlock.block_index).all()
        assert [(b.event_type, b.payload["channel"]) for b in blocks] == [
            ("sensor_dead", "humidity"),
            ("sensor_recovered", "humidity"),
        ]
        assert ledger_service.verify(db, device.id).valid is True


def test_a_dead_sensor_is_a_warning_condition():
    rollup = ConditionRollup(None)
    rollup.on_decision(_decision(stale=["humidity"]))
    assert rollup.level("pump-01") == HealthState.warning
    rollup.on_decision(_decision(i=1))
    assert rollup.level("pump-01") == HealthState.healthy


def test_a_dead_sensor_raises_one_warning_alert(factory):
    """D053: one alert per death, none for the recovery."""
    from app.models import Alert

    recorder = SensorHealthLedger(factory)
    for i, stale in enumerate([[], ["pressure"], ["pressure"], []]):
        recorder.record(_decision(stale=stale, i=i))
    with factory() as db:
        alerts = db.query(Alert).all()
        assert [(a.type.value, a.severity.value, a.channel) for a in alerts] == [
            ("fault", "warning", "pressure")
        ]
