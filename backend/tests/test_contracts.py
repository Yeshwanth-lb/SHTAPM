"""M2 contract tests — canonical telemetry/decision/ledger (D006/D007).

Proves valid canonical examples are accepted and clearly-invalid structures
(missing fields, wrong enums, out-of-range scores, renamed/extra keys, and the
superseded PRD shorthand) are rejected. No MQTT/simulator/ML involved.
"""

import pytest
from app.schemas.contracts import (
    DecisionMessage,
    LedgerMessage,
    TelemetryMessage,
)
from pydantic import ValidationError

VALID_TELEMETRY = {
    "device_id": "pump-01",
    "ts": "2026-08-09T12:00:00.000Z",
    "sensors": {
        "temperature": 24.5,
        "vibration": 0.03,
        "pressure": 1013.2,
        "humidity": 41.0,
        "gas": 120.0,
        "current": 0.42,
    },
    "sample_seq": 123,
}

VALID_DECISION = {
    "device_id": "pump-01",
    "ts": "2026-08-09T12:00:03.000Z",
    "anomaly": {
        "flag": True,
        "severity": 0.82,
        "attribution": "attack",
        "reason": "pressure vs current",
    },
    "trust": {
        "temperature": 0.95,
        "vibration": 0.93,
        "pressure": 0.21,
        "humidity": 0.90,
        "gas": 0.88,
        "current": 0.97,
    },
    "health": "warning",
    "failure_eta": 142,
    "rl_action": "isolate",
    "isolated": ["pressure"],
    "substituted": ["pressure"],
}

VALID_LEDGER = {
    "device_id": "pump-01",
    "ts": "2026-08-09T12:00:03.100Z",
    "block_index": 57,
    "event": "isolate",
    "payload_hash": "9f0c",
    "prev_hash": "7a3b",
    "this_hash": "a1b2",
}


# ---- valid examples accepted -------------------------------------------------


def test_valid_telemetry_accepted():
    TelemetryMessage.model_validate(VALID_TELEMETRY)


def test_valid_decision_accepted():
    DecisionMessage.model_validate(VALID_DECISION)


def test_valid_ledger_accepted():
    LedgerMessage.model_validate(VALID_LEDGER)


def test_empty_heal_arrays_valid():
    d = {**VALID_DECISION, "isolated": [], "substituted": [], "rl_action": "continue"}
    DecisionMessage.model_validate(d)


# ---- invalid structures rejected ---------------------------------------------


def test_telemetry_missing_sample_seq_rejected():
    bad = {k: v for k, v in VALID_TELEMETRY.items() if k != "sample_seq"}
    with pytest.raises(ValidationError):
        TelemetryMessage.model_validate(bad)


def test_telemetry_prd_shorthand_rejected():
    # ruling A: "temp"/"vib" are superseded and must fail (extra + missing).
    bad = {
        **VALID_TELEMETRY,
        "sensors": {
            "temp": 24.5,
            "vib": 0.03,
            "pressure": 1013.2,
            "humidity": 41.0,
            "gas": 120.0,
            "current": 0.42,
        },
    }
    with pytest.raises(ValidationError):
        TelemetryMessage.model_validate(bad)


def test_telemetry_extra_sensor_rejected():
    bad = {**VALID_TELEMETRY, "sensors": {**VALID_TELEMETRY["sensors"], "flow": 1.0}}
    with pytest.raises(ValidationError):
        TelemetryMessage.model_validate(bad)


def test_decision_bad_attribution_rejected():
    bad = {**VALID_DECISION, "anomaly": {**VALID_DECISION["anomaly"], "attribution": "spoof"}}
    with pytest.raises(ValidationError):
        DecisionMessage.model_validate(bad)


def test_decision_bad_rl_action_rejected():
    bad = {**VALID_DECISION, "rl_action": "shutdown"}
    with pytest.raises(ValidationError):
        DecisionMessage.model_validate(bad)


def test_decision_trust_out_of_range_rejected():
    bad = {**VALID_DECISION, "trust": {**VALID_DECISION["trust"], "temperature": 1.5}}
    with pytest.raises(ValidationError):
        DecisionMessage.model_validate(bad)


def test_decision_bad_channel_rejected():
    bad = {**VALID_DECISION, "isolated": ["flow"]}
    with pytest.raises(ValidationError):
        DecisionMessage.model_validate(bad)


def test_decision_nested_healing_rejected():
    # ruling C: nested healing:{} shape is superseded and must fail.
    bad = {k: v for k, v in VALID_DECISION.items() if k not in ("isolated", "substituted")}
    bad["healing"] = {"isolated": ["pressure"], "substituted": ["pressure"]}
    with pytest.raises(ValidationError):
        DecisionMessage.model_validate(bad)


def test_ledger_missing_payload_hash_rejected():
    # ruling D: payload_hash is required in the canonical ledger message.
    bad = {k: v for k, v in VALID_LEDGER.items() if k != "payload_hash"}
    with pytest.raises(ValidationError):
        LedgerMessage.model_validate(bad)
