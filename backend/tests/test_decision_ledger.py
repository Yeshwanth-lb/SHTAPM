"""DecisionLedgerRecorder tests (SQLite, no MQTT/broker).

The property that matters: blocks are written on ENTRY to a state, never for
every cycle it persists. At 1 Hz, level-triggering would bury real events under
~86,400 blocks per device per day.
"""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Device, LedgerBlock  # noqa: E402
from app.schemas.contracts import Attribution, TrustScores  # noqa: E402
from app.schemas.decision_diagnostic import (  # noqa: E402
    ChannelAttribution,
    DecisionDiagnosticMessage,
)
from app.services import ledger as ledger_service  # noqa: E402
from app.services.decision_ledger import (  # noqa: E402
    EVENT_ISOLATE,
    EVENT_TRUST_DROP,
    DecisionLedgerRecorder,
)
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_NONE_ATTRIBUTION = {
    ch: ChannelAttribution(attribution=Attribution.none, reason="")
    for ch in ("temperature", "vibration", "pressure", "humidity", "gas", "current")
}


def _message(*, candidates=(), substituted=(), seq=0, ts="2026-09-18T12:00:00.000Z", trust=0.9):
    return DecisionDiagnosticMessage(
        device_id="pump-01",
        ts=ts,
        sample_seq=seq,
        window_start_index=0,
        window_end_index=30,
        anomaly_flag=False,
        anomaly_severity=0.0,
        trust=TrustScores(
            temperature=trust,
            vibration=trust,
            pressure=trust,
            humidity=trust,
            gas=trust,
            current=trust,
        ),
        attribution=_NONE_ATTRIBUTION,
        isolation_candidates=list(candidates),
        tracked_isolation_candidates=list(candidates),
        substituted_channels=list(substituted),
    )


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def recorder(session_factory) -> DecisionLedgerRecorder:
    return DecisionLedgerRecorder(session_factory)


def _blocks(session_factory) -> list[LedgerBlock]:
    with session_factory() as db:
        return db.query(LedgerBlock).order_by(LedgerBlock.block_index).all()


def test_nothing_chained_while_everything_is_healthy(recorder, session_factory):
    for seq in range(5):
        recorder.record(_message(seq=seq))
    assert _blocks(session_factory) == []


def test_trust_drop_is_chained_on_entry(recorder, session_factory):
    recorder.record(_message(candidates=["current"], trust=0.2, seq=1))

    blocks = _blocks(session_factory)
    assert len(blocks) == 1
    assert blocks[0].event_type == EVENT_TRUST_DROP
    assert blocks[0].payload["channel"] == "current"
    assert blocks[0].payload["trust"] == 0.2


def test_sustained_condition_does_not_chain_every_cycle(recorder, session_factory):
    """The whole point: 300 cycles in the same state produce ONE block."""
    for seq in range(300):
        recorder.record(_message(candidates=["current"], trust=0.2, seq=seq))

    blocks = _blocks(session_factory)
    assert len(blocks) == 1, f"expected edge-triggered chaining, got {len(blocks)} blocks"


def test_recovery_then_relapse_chains_again(recorder, session_factory):
    """A channel that recovers and degrades again is a NEW event, not a
    duplicate of the first -- otherwise a repeat attack would be invisible."""
    recorder.record(_message(candidates=["current"], trust=0.2, seq=1))
    recorder.record(_message(candidates=[], trust=0.9, seq=2))  # recovered
    recorder.record(_message(candidates=["current"], trust=0.2, seq=3))

    blocks = _blocks(session_factory)
    assert len(blocks) == 2
    assert [b.event_type for b in blocks] == [EVENT_TRUST_DROP, EVENT_TRUST_DROP]


def test_substitution_is_chained_as_isolate(recorder, session_factory):
    recorder.record(_message(candidates=["current"], substituted=["current"], trust=0.2))

    events = [b.event_type for b in _blocks(session_factory)]
    assert EVENT_ISOLATE in events
    assert EVENT_TRUST_DROP in events


def test_multiple_channels_each_get_their_own_block(recorder, session_factory):
    recorder.record(_message(candidates=["current", "vibration"], trust=0.2))

    blocks = _blocks(session_factory)
    assert len(blocks) == 2
    assert {b.payload["channel"] for b in blocks} == {"current", "vibration"}


def test_chain_stays_verifiable(recorder, session_factory):
    """Chaining real events must not break the hash chain the verifier walks."""
    recorder.record(_message(candidates=["current"], trust=0.2, seq=1))
    recorder.record(_message(candidates=[], trust=0.9, seq=2))
    recorder.record(_message(candidates=["vibration"], substituted=["vibration"], trust=0.2, seq=3))

    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        result = ledger_service.verify(db, device.id)
    assert result.valid is True
    assert result.broken_at is None


def test_tamper_is_still_caught_after_real_events(recorder, session_factory):
    """AC5's actual requirement: a live tamper must be detected."""
    recorder.record(_message(candidates=["current"], trust=0.2, seq=1))
    recorder.record(_message(candidates=[], trust=0.9, seq=2))
    recorder.record(_message(candidates=["current"], trust=0.2, seq=3))

    with session_factory() as db:
        device = db.query(Device).filter(Device.device_id == "pump-01").one()
        block = db.query(LedgerBlock).order_by(LedgerBlock.block_index).first()
        block.payload = {**block.payload, "trust": 0.99}  # rewrite history
        db.commit()

    with session_factory() as db:
        result = ledger_service.verify(db, device.id)
    assert result.valid is False
    assert result.broken_at == 0


def test_ledger_failure_never_raises_into_ingestion(session_factory):
    """A ledger fault must not stop decision ingestion."""

    class _Exploding:
        def __call__(self, *a, **k):
            raise RuntimeError("db gone")

    recorder = DecisionLedgerRecorder(_Exploding())
    recorder.record(_message(candidates=["current"], trust=0.2))  # must not raise
