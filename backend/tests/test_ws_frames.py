"""M3.4 unit tests — WS telemetry frame envelope (Doc05 §05.8, ruling E)."""

from app.schemas.contracts import SensorReadings, TelemetryMessage
from app.ws.frames import telemetry_frame


def _msg(seq: int = 7) -> TelemetryMessage:
    return TelemetryMessage(
        device_id="pump-01",
        ts="2026-08-09T12:00:00.000Z",
        sensors=SensorReadings(
            temperature=26.0, vibration=0.03, pressure=1013.0,
            humidity=45.0, gas=150.0, current=0.42,
        ),
        sample_seq=seq,
    )


def test_frame_is_flat_type_plus_payload():
    f = telemetry_frame(_msg())
    assert f["type"] == "telemetry"
    assert set(f.keys()) == {"type", "device_id", "ts", "sensors", "sample_seq"}


def test_frame_payload_matches_frozen_contract():
    f = telemetry_frame(_msg(seq=7))
    assert f["device_id"] == "pump-01"
    assert f["sample_seq"] == 7
    assert set(f["sensors"].keys()) == {
        "temperature", "vibration", "pressure", "humidity", "gas", "current",
    }
    payload = {k: v for k, v in f.items() if k != "type"}
    TelemetryMessage.model_validate(payload)  # round-trips through the contract
