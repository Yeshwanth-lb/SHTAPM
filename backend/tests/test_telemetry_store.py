"""M3.3 unit tests — in-memory telemetry store."""

from app.schemas.contracts import SensorReadings, TelemetryMessage
from app.services.telemetry_store import TelemetryStore


def _msg(device_id: str, seq: int) -> TelemetryMessage:
    return TelemetryMessage(
        device_id=device_id,
        ts="2026-08-09T12:00:00.000Z",
        sensors=SensorReadings(
            temperature=26.0,
            vibration=0.03,
            pressure=1013.0,
            humidity=45.0,
            gas=150.0,
            current=0.42,
        ),
        sample_seq=seq,
    )


def test_update_and_latest():
    store = TelemetryStore()
    store.update(_msg("pump-01", 0))
    store.update(_msg("pump-01", 1))
    assert store.latest("pump-01").sample_seq == 1
    assert store.count == 2


def test_latest_unknown_device_is_none():
    assert TelemetryStore().latest("nope") is None


def test_multiple_devices_tracked_independently():
    store = TelemetryStore()
    store.update(_msg("pump-01", 5))
    store.update(_msg("pump-02", 9))
    assert store.latest("pump-01").sample_seq == 5
    assert store.latest("pump-02").sample_seq == 9
    assert set(store.devices()) == {"pump-01", "pump-02"}
    assert store.count == 2
