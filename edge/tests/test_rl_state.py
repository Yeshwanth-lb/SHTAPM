"""Tests for edge/rl/state.py (FR-RL1 state representation). Pure-Python,
no torch dependency -- no test here requires the prognosis model."""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS

from edge.rl.state import (
    MISSING_PROGNOSIS_FILL_VALUE,
    STATE_FIELD_ORDER,
    STATE_WIDTH,
    RLState,
    build_rl_state,
)
from edge.trust.beta import classify
from edge.trust.engine import TrustReading

_DEFAULT_TRUST_FIXTURE = 0.8


def _trust_readings(overrides: dict[str, float] | None = None) -> dict[str, TrustReading]:
    overrides = overrides or {}
    return {
        ch: TrustReading(
            channel=ch,
            g=0.0,
            trust=overrides.get(ch, _DEFAULT_TRUST_FIXTURE),
            band=classify(overrides.get(ch, _DEFAULT_TRUST_FIXTURE)),
        )
        for ch in CHANNELS
    }


def _trust_values(overrides: dict[str, float] | None = None) -> dict[str, float]:
    overrides = overrides or {}
    return {ch: overrides.get(ch, _DEFAULT_TRUST_FIXTURE) for ch in CHANNELS}


# ---------------------------------------------------------------------------
# Ordering and width
# ---------------------------------------------------------------------------


def test_state_width_is_nine_per_fr_rl1():
    assert STATE_WIDTH == 9
    assert len(STATE_FIELD_ORDER) == 9


def test_state_field_order_matches_fr_rl1_exactly():
    expected = ("health", "anomaly_flag", *(f"trust_{ch}" for ch in CHANNELS), "failure_eta")
    assert STATE_FIELD_ORDER == expected


def test_to_vector_has_expected_width():
    state = RLState(health=0.5, anomaly_flag=False, trust=_trust_values(), failure_eta=10.0)
    assert len(state.to_vector()) == STATE_WIDTH


# ---------------------------------------------------------------------------
# Valid conversion
# ---------------------------------------------------------------------------


def test_to_vector_places_fields_in_documented_order():
    trust = _trust_values(
        {
            "temperature": 0.1,
            "vibration": 0.2,
            "pressure": 0.3,
            "humidity": 0.4,
            "gas": 0.5,
            "current": 0.6,
        }
    )
    state = RLState(health=0.9, anomaly_flag=True, trust=trust, failure_eta=42.0)

    vector = state.to_vector()

    assert vector[0] == pytest.approx(0.9)  # health
    assert vector[1] == 1.0  # anomaly_flag (True -> 1.0)
    assert vector[2:8] == (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)  # T1..T6, CHANNELS order
    assert vector[8] == pytest.approx(42.0)  # failure_eta


def test_anomaly_flag_false_encodes_as_zero():
    state = RLState(health=0.5, anomaly_flag=False, trust=_trust_values(), failure_eta=1.0)
    assert state.to_vector()[1] == 0.0


def test_build_rl_state_extracts_trust_from_trust_reading_mapping():
    state = build_rl_state(
        health=0.7,
        anomaly_flag=False,
        trust=_trust_readings(),
        failure_eta=5.0,
    )
    assert state.trust == _trust_values()


def test_build_rl_state_passes_through_metadata():
    state = build_rl_state(
        health=0.5,
        anomaly_flag=False,
        trust=_trust_readings(),
        failure_eta=1.0,
        execution_mode="simulation",
        prognosis_data_source="synthetic",
        health_label_source="synthetic_policy_fixture",
    )
    assert state.execution_mode == "simulation"
    assert state.prognosis_data_source == "synthetic"
    assert state.health_label_source == "synthetic_policy_fixture"


def test_metadata_defaults_to_none():
    state = RLState(health=0.5, anomaly_flag=False, trust=_trust_values(), failure_eta=1.0)
    assert state.execution_mode is None
    assert state.prognosis_data_source is None
    assert state.health_label_source is None


# ---------------------------------------------------------------------------
# Invalid values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_health", [-0.1, 1.1, float("nan"), float("inf")])
def test_out_of_range_or_non_finite_health_raises(bad_health):
    with pytest.raises(ValueError):
        RLState(health=bad_health, anomaly_flag=False, trust=_trust_values(), failure_eta=1.0)


@pytest.mark.parametrize("bad_eta", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_failure_eta_raises(bad_eta):
    with pytest.raises(ValueError):
        RLState(health=0.5, anomaly_flag=False, trust=_trust_values(), failure_eta=bad_eta)


def test_out_of_range_trust_raises():
    with pytest.raises(ValueError):
        RLState(
            health=0.5,
            anomaly_flag=False,
            trust=_trust_values({"vibration": 1.5}),
            failure_eta=1.0,
        )


def test_missing_trust_channel_raises():
    incomplete = _trust_values()
    del incomplete["vibration"]
    with pytest.raises(ValueError, match="missing"):
        RLState(health=0.5, anomaly_flag=False, trust=incomplete, failure_eta=1.0)


def test_unknown_trust_channel_raises():
    extra = _trust_values()
    extra["not_a_channel"] = 0.5
    with pytest.raises(ValueError, match="unknown"):
        RLState(health=0.5, anomaly_flag=False, trust=extra, failure_eta=1.0)


def test_build_rl_state_missing_trust_channel_raises_before_construction():
    incomplete = _trust_readings()
    del incomplete["gas"]
    with pytest.raises(ValueError, match="missing"):
        build_rl_state(health=0.5, anomaly_flag=False, trust=incomplete, failure_eta=1.0)


# ---------------------------------------------------------------------------
# Missing / unavailable prognosis data
# ---------------------------------------------------------------------------


def test_prognosis_available_true_when_both_present():
    state = RLState(health=0.5, anomaly_flag=False, trust=_trust_values(), failure_eta=1.0)
    assert state.prognosis_available is True


def test_prognosis_available_false_when_health_missing():
    state = RLState(health=None, anomaly_flag=False, trust=_trust_values(), failure_eta=1.0)
    assert state.prognosis_available is False


def test_prognosis_available_false_when_failure_eta_missing():
    state = RLState(health=0.5, anomaly_flag=False, trust=_trust_values(), failure_eta=None)
    assert state.prognosis_available is False


def test_prognosis_available_false_when_both_missing():
    state = RLState(health=None, anomaly_flag=False, trust=_trust_values(), failure_eta=None)
    assert state.prognosis_available is False


def test_to_vector_substitutes_fill_value_for_missing_health_and_eta():
    state = RLState(health=None, anomaly_flag=True, trust=_trust_values(), failure_eta=None)
    vector = state.to_vector()
    assert vector[0] == MISSING_PROGNOSIS_FILL_VALUE
    assert vector[8] == MISSING_PROGNOSIS_FILL_VALUE
    assert len(vector) == STATE_WIDTH  # width is preserved even when data is missing


def test_none_health_and_eta_do_not_raise():
    # None is a valid, first-class state -- must not be rejected by validation.
    RLState(health=None, anomaly_flag=False, trust=_trust_values(), failure_eta=None)
