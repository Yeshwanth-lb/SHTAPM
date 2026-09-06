"""Tests for edge/pipeline/decision_diagnostic.py -- the WindowOutcome ->
DecisionDiagnosticMessage mapping and the best-effort MQTT publisher.

Not the frozen DecisionMessage/`.../decision` topic -- see that module's
own docstring and backend/app/schemas/decision_diagnostic.py's docstring
for why a separate schema/topic exists.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS, Attribution
from app.schemas.decision_diagnostic import DecisionDiagnosticMessage
from pydantic import ValidationError

from edge.anomaly.attribution import AttributionResult
from edge.anomaly.detector import AnomalyResult
from edge.anomaly.pipeline import WindowOutcome
from edge.anomaly.preprocess import Window
from edge.pipeline.decision_diagnostic import (
    DecisionDiagnosticPublisher,
    build_decision_diagnostic_message,
)
from edge.pipeline.isolation_tracker import IsolationTrackerResult
from edge.pipeline.monitor import RawChannelValues
from edge.trust.beta import TrustBand
from edge.trust.engine import TrustReading


def _window_outcome(
    *,
    flag: bool = False,
    severity: float = 0.0,
    trust_value: float = 0.8,
    band: TrustBand = TrustBand.TRUSTED,
    attribution: Attribution = Attribution.none,
) -> WindowOutcome:
    window = Window(start_index=0, end_index=30, features={ch: (0.0,) * 30 for ch in CHANNELS})
    trust = {
        ch: TrustReading(channel=ch, g=1.0, trust=trust_value, band=band) for ch in CHANNELS
    }
    attributions = {
        ch: AttributionResult(channel=ch, attribution=attribution, reason="")
        for ch in CHANNELS
    }
    return WindowOutcome(
        window=window,
        anomaly=AnomalyResult(flag=flag, severity=severity),
        channel_flags=dict.fromkeys(CHANNELS, False),
        trust=trust,
        attribution=attributions,
    )


def _raw_values(ts: str = "2026-09-06T12:00:00.000Z", sample_seq: int = 29) -> RawChannelValues:
    return RawChannelValues(ts=ts, sample_seq=sample_seq, values=dict.fromkeys(CHANNELS, 1.0))


def _tracked(
    *, candidates: frozenset[str] = frozenset(), tracked: frozenset[str] = frozenset()
) -> IsolationTrackerResult:
    return IsolationTrackerResult(
        candidates_this_cycle=candidates, tracked_channels=tracked, reasons={}
    )


# ---------------------------------------------------------------------------
# build_decision_diagnostic_message -- payload validation + mapping
# ---------------------------------------------------------------------------


def test_maps_anomaly_and_trust_fields_directly():
    outcome = _window_outcome(flag=True, severity=0.75, trust_value=0.42, band=TrustBand.SUSPICIOUS)
    msg = build_decision_diagnostic_message("pump-01", outcome, _tracked(), _raw_values())

    assert isinstance(msg, DecisionDiagnosticMessage)
    assert msg.device_id == "pump-01"
    assert msg.anomaly_flag is True
    assert msg.anomaly_severity == 0.75
    for ch in CHANNELS:
        assert getattr(msg.trust, ch) == 0.42


def test_maps_ts_sample_seq_and_window_indices_from_raw_and_outcome():
    outcome = _window_outcome()
    raw = _raw_values(ts="2026-09-06T13:30:00.500Z", sample_seq=41)
    msg = build_decision_diagnostic_message("pump-01", outcome, _tracked(), raw)

    assert msg.ts == "2026-09-06T13:30:00.500Z"
    assert msg.sample_seq == 41
    assert msg.window_start_index == 0
    assert msg.window_end_index == 30


def test_preserves_full_per_channel_attribution_no_reduction():
    """No single window-level attribution/reason is invented -- every
    channel's own attribution+reason survives into the payload."""
    outcome = _window_outcome(attribution=Attribution.attack)
    outcome.attribution["vibration"] = AttributionResult(
        channel="vibration", attribution=Attribution.fault, reason="differs from the rest"
    )
    msg = build_decision_diagnostic_message("pump-01", outcome, _tracked(), _raw_values())

    assert set(msg.attribution) == set(CHANNELS)
    assert msg.attribution["vibration"].attribution == Attribution.fault
    assert msg.attribution["vibration"].reason == "differs from the rest"
    assert msg.attribution["temperature"].attribution == Attribution.attack


def test_maps_isolation_candidates_and_tracked_channels_never_isolated_field():
    tracked = _tracked(
        candidates=frozenset({"vibration"}), tracked=frozenset({"vibration", "current"})
    )
    msg = build_decision_diagnostic_message("pump-01", _window_outcome(), tracked, _raw_values())

    assert msg.isolation_candidates == ["vibration"]
    assert sorted(msg.tracked_isolation_candidates) == ["current", "vibration"]
    # The schema itself has no "isolated"/"substituted" field at all --
    # confirmed structurally, not just by omission from this mapping.
    assert "isolated" not in type(msg).model_fields
    assert "substituted" not in type(msg).model_fields


def test_self_identifies_as_diagnostic_not_authoritative():
    msg = build_decision_diagnostic_message("pump-01", _window_outcome(), _tracked(), _raw_values())
    assert msg.execution_mode == "live"
    assert msg.data_source == "edge_live_pipeline"
    assert msg.model_status == "diagnostic_unvalidated"


def test_no_health_failure_eta_rl_action_or_substituted_fields_exist():
    """Structural guard: this schema must never grow the fields the frozen
    DecisionMessage requires but nothing here can honestly compute."""
    forbidden = {"health", "failure_eta", "rl_action", "substituted", "isolated"}
    assert forbidden.isdisjoint(DecisionDiagnosticMessage.model_fields)


# ---------------------------------------------------------------------------
# Deterministic serialization
# ---------------------------------------------------------------------------


def test_serialization_is_deterministic_for_identical_input():
    outcome = _window_outcome(flag=True, severity=0.3, trust_value=0.6)
    tracked = _tracked(candidates=frozenset({"gas"}), tracked=frozenset({"gas"}))
    raw = _raw_values()
    msg1 = build_decision_diagnostic_message("pump-01", outcome, tracked, raw)
    msg2 = build_decision_diagnostic_message("pump-01", outcome, tracked, raw)
    assert msg1.model_dump_json() == msg2.model_dump_json()


def test_round_trips_through_json_validation():
    msg = build_decision_diagnostic_message("pump-01", _window_outcome(), _tracked(), _raw_values())
    payload = msg.model_dump_json()
    rebuilt = DecisionDiagnosticMessage.model_validate_json(payload)
    assert rebuilt == msg


def test_extra_field_rejected_like_the_frozen_contract():
    msg = build_decision_diagnostic_message("pump-01", _window_outcome(), _tracked(), _raw_values())
    data = msg.model_dump(mode="json")
    data["unexpected_field"] = 1
    with pytest.raises(ValidationError):
        DecisionDiagnosticMessage.model_validate(data)


# ---------------------------------------------------------------------------
# DecisionDiagnosticPublisher -- best-effort, never raises
# ---------------------------------------------------------------------------


def test_publish_before_start_is_a_silent_no_op():
    publisher = DecisionDiagnosticPublisher(device_id="pump-01")
    msg = build_decision_diagnostic_message("pump-01", _window_outcome(), _tracked(), _raw_values())
    publisher.publish(msg)  # must not raise


def test_publish_swallows_client_exceptions():
    class _BrokenClient:
        def publish(self, *a, **kw):
            raise RuntimeError("boom")

    publisher = DecisionDiagnosticPublisher(device_id="pump-01")
    publisher._client = _BrokenClient()
    msg = build_decision_diagnostic_message("pump-01", _window_outcome(), _tracked(), _raw_values())
    publisher.publish(msg)  # must not raise


def test_publish_calls_client_publish_with_correct_topic_and_qos():
    calls = []

    class _RecordingClient:
        def publish(self, topic, payload, qos=0):
            calls.append((topic, payload, qos))

    publisher = DecisionDiagnosticPublisher(device_id="pump-07")
    publisher._client = _RecordingClient()
    msg = build_decision_diagnostic_message("pump-07", _window_outcome(), _tracked(), _raw_values())
    publisher.publish(msg)

    assert len(calls) == 1
    topic, payload, qos = calls[0]
    assert topic == "shtapm/pump-07/decision_diagnostic"
    assert qos == 0
    assert DecisionDiagnosticMessage.model_validate_json(payload) == msg


def test_stop_before_start_does_not_raise():
    DecisionDiagnosticPublisher(device_id="pump-01").stop()


def test_stop_swallows_client_disconnect_exceptions():
    class _BrokenClient:
        def loop_stop(self):
            raise RuntimeError("boom")

        def disconnect(self):
            raise RuntimeError("boom")

    publisher = DecisionDiagnosticPublisher(device_id="pump-01")
    publisher._client = _BrokenClient()
    publisher.stop()  # must not raise
    assert publisher._client is None


def test_start_failure_leaves_publisher_inert_not_raising(monkeypatch):
    """start() is best-effort too -- e.g. a bad host/port must never raise
    into edge/main.py's startup."""
    import edge.pipeline.decision_diagnostic as module

    class _ExplodingClient:
        def connect_async(self, host, port):
            raise OSError("no such host")

    class _FakeMqttModule:
        @staticmethod
        def Client():
            return _ExplodingClient()

    monkeypatch.setitem(__import__("sys").modules, "paho.mqtt.client", _FakeMqttModule())
    publisher = module.DecisionDiagnosticPublisher(device_id="pump-01")
    publisher.start("bad-host", 1)  # must not raise
    assert publisher._client is None
    publisher.publish(
        build_decision_diagnostic_message("pump-01", _window_outcome(), _tracked(), _raw_values())
    )  # still a no-op, still must not raise
