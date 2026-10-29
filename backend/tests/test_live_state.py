"""Live physics view (D054): latest motor state + twin values per device."""

from __future__ import annotations

from app.schemas.contracts import Attribution, TrustScores
from app.schemas.decision_diagnostic import ChannelAttribution, DecisionDiagnosticMessage
from app.services.live_state import LiveStateRegistry

CHANNELS = ("temperature", "vibration", "pressure", "humidity", "gas", "current")


def _message(seq: int, **extra) -> DecisionDiagnosticMessage:
    return DecisionDiagnosticMessage(
        device_id="pump-01",
        ts=f"2026-10-29T10:00:0{seq}.000Z",
        sample_seq=seq,
        window_start_index=0,
        window_end_index=30,
        anomaly_flag=False,
        anomaly_severity=0.0,
        trust=TrustScores(**dict.fromkeys(CHANNELS, 0.9)),
        attribution={
            ch: ChannelAttribution(attribution=Attribution.none, reason="") for ch in CHANNELS
        },
        isolation_candidates=[],
        tracked_isolation_candidates=[],
        **extra,
    )


def test_registry_keeps_the_newest_decision_per_device():
    registry = LiveStateRegistry()
    assert registry.get("pump-01") is None
    registry.update(_message(1))
    state = {"state": "running", "median": 0.6, "idle_max": 0.14, "running_min": 0.31}
    registry.update(
        _message(
            2, motor_state={"current": state, "vibration": state}, twin_values={"current": 0.7}
        )
    )
    latest = registry.get("pump-01")
    assert latest.sample_seq == 2
    assert latest.motor_state["current"].state == "running"
    assert latest.twin_values == {"current": 0.7}


def test_an_older_edge_without_the_fields_is_still_valid():
    message = _message(1)
    assert message.motor_state is None and message.twin_values == {}
