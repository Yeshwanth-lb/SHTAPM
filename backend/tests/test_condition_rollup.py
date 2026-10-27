"""Device condition rollup (D043): presentation state from attribution,
isolation and safe-stop -- never a prognosis."""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Device  # noqa: E402
from app.schemas.actuation import ActuationStatus  # noqa: E402
from app.schemas.contracts import Attribution, HealthState, TrustScores  # noqa: E402
from app.schemas.decision_diagnostic import (  # noqa: E402
    ChannelAttribution,
    DecisionDiagnosticMessage,
)
from app.services.condition import ConditionRollup  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

CHANNELS = ("temperature", "vibration", "pressure", "humidity", "gas", "current")


def _decision(label: Attribution = Attribution.none, isolated=(), i: int = 0):
    clean = ChannelAttribution(attribution=Attribution.none, reason="")
    attribution = {ch: clean for ch in CHANNELS}
    if label != Attribution.none:
        attribution["current"] = ChannelAttribution(attribution=label, reason="x")
    return DecisionDiagnosticMessage(
        device_id="pump-01",
        ts=f"2026-10-27T10:00:{i % 60:02d}.000Z",
        sample_seq=i,
        window_start_index=0,
        window_end_index=30,
        anomaly_flag=label != Attribution.none,
        anomaly_severity=0.5,
        trust=TrustScores(**{ch: 0.9 for ch in CHANNELS}),
        attribution=attribution,
        isolation_candidates=list(isolated),
        tracked_isolation_candidates=list(isolated),
    )


def _actuation(cause: str, latched: bool, relay: str = "off") -> ActuationStatus:
    return ActuationStatus(
        device_id="pump-01",
        ts="2026-10-27T10:00:00.000Z",
        relay=relay,
        cause=cause,
        reason="r",
        latched=latched,
        hardware=False,
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


def _stored(factory) -> HealthState:
    with factory() as db:
        return db.query(Device).one().health_state


def test_clean_decisions_are_healthy(factory):
    rollup = ConditionRollup(factory)
    for i in range(10):
        rollup.on_decision(_decision(i=i))
    assert rollup.level("pump-01") == HealthState.healthy


def test_a_single_noisy_window_does_not_change_the_colour(factory):
    rollup = ConditionRollup(factory)
    for i in range(9):
        rollup.on_decision(_decision(i=i))
    rollup.on_decision(_decision(Attribution.attack, i=9))
    assert rollup.level("pump-01") == HealthState.healthy


def test_sustained_faults_are_a_warning_and_written_to_the_device(factory):
    rollup = ConditionRollup(factory)
    for i in range(5):
        rollup.on_decision(_decision(Attribution.fault, i=i))
    assert rollup.level("pump-01") == HealthState.warning
    assert _stored(factory) == HealthState.warning


def test_sustained_attacks_are_critical(factory):
    rollup = ConditionRollup(factory)
    for i in range(5):
        rollup.on_decision(_decision(Attribution.attack, i=i))
    assert rollup.level("pump-01") == HealthState.critical


def test_isolation_is_a_warning_and_an_attack_on_top_is_critical(factory):
    rollup = ConditionRollup(factory)
    rollup.on_decision(_decision(isolated=["current"]))
    assert rollup.level("pump-01") == HealthState.warning
    rollup.on_decision(_decision(Attribution.attack, isolated=["current"], i=1))
    assert rollup.level("pump-01") == HealthState.critical


def test_a_latched_autonomous_safe_stop_is_critical_until_restarted(factory):
    rollup = ConditionRollup(factory)
    rollup.on_decision(_decision())
    rollup.on_actuation(_actuation("dry_run", latched=True))
    assert rollup.level("pump-01") == HealthState.critical
    rollup.on_actuation(_actuation("command", latched=False, relay="on"))
    assert rollup.level("pump-01") == HealthState.healthy
    assert _stored(factory) == HealthState.healthy


def test_an_operator_stop_is_not_a_fault(factory):
    rollup = ConditionRollup(factory)
    rollup.on_actuation(_actuation("command", latched=False))
    assert rollup.level("pump-01") == HealthState.healthy


def test_recovery_returns_to_healthy(factory):
    rollup = ConditionRollup(factory)
    for i in range(5):
        rollup.on_decision(_decision(Attribution.attack, isolated=["current"], i=i))
    assert rollup.level("pump-01") == HealthState.critical
    for i in range(5, 15):
        rollup.on_decision(_decision(i=i))
    assert rollup.level("pump-01") == HealthState.healthy


def test_unknown_device_is_tolerated():
    rollup = ConditionRollup(None)
    rollup.on_decision(_decision())
    assert rollup.level("pump-01") == HealthState.healthy
