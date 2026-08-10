"""C2 tests — shared build_telemetry() (contract-compatible, no schema change)."""

import pytest
from app.schemas.build import build_telemetry
from app.schemas.contracts import TelemetryMessage
from pydantic import ValidationError

SENSORS = {
    "temperature": 24.5,
    "vibration": 0.03,
    "pressure": 1013.2,
    "humidity": 41.0,
    "gas": 120.0,
    "current": 0.42,
}


def test_builds_frozen_message():
    m = build_telemetry("pump-01", "2026-08-10T12:00:00.000Z", SENSORS, 7)
    assert isinstance(m, TelemetryMessage)
    assert m.device_id == "pump-01" and m.sample_seq == 7
    # serialization identical to a hand-built message (contract-compatible)
    hand = TelemetryMessage.model_validate(
        {
            "device_id": "pump-01",
            "ts": "2026-08-10T12:00:00.000Z",
            "sensors": SENSORS,
            "sample_seq": 7,
        }
    )
    assert m.model_dump_json() == hand.model_dump_json()


def test_missing_channel_rejected():
    bad = {k: v for k, v in SENSORS.items() if k != "gas"}
    with pytest.raises(ValidationError):
        build_telemetry("pump-01", "t", bad, 0)


def test_extra_channel_rejected():
    bad = {**SENSORS, "flow": 1.0}
    with pytest.raises(ValidationError):
        build_telemetry("pump-01", "t", bad, 0)
