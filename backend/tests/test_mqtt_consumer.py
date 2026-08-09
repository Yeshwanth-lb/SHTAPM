"""M3.3 unit tests — backend telemetry consumer (no paho, no broker)."""

from app.mqtt.consumer import TelemetryConsumer, device_from_topic
from app.services.telemetry_store import TelemetryStore


class FakeMsg:
    def __init__(self, topic: str, payload):
        self.topic = topic
        self.payload = payload


def _valid_payload(device_id="pump-01", seq=0) -> str:
    return (
        '{"device_id":"%s","ts":"2026-08-09T12:00:00.000Z",'
        '"sensors":{"temperature":26.0,"vibration":0.03,"pressure":1013.0,'
        '"humidity":45.0,"gas":150.0,"current":0.42},"sample_seq":%d}' % (device_id, seq)
    )


def _consumer():
    store = TelemetryStore()
    return TelemetryConsumer(store), store


def test_device_from_topic():
    assert device_from_topic("shtapm/pump-01/telemetry") == "pump-01"
    assert device_from_topic("shtapm/pump-01/decision") is None
    assert device_from_topic("garbage") is None


def test_valid_telemetry_accepted():
    c, store = _consumer()
    c.handle(FakeMsg("shtapm/pump-01/telemetry", _valid_payload().encode()))
    assert store.count == 1
    assert store.latest("pump-01").device_id == "pump-01"
    assert c.error_count == 0


def test_malformed_json_handled_safely():
    c, store = _consumer()
    c.handle(FakeMsg("shtapm/pump-01/telemetry", b"not-json{"))
    assert store.count == 0
    assert c.error_count == 1  # counted, not crashed


def test_contract_invalid_rejected():
    c, store = _consumer()
    # bad enum-free but out-of-contract: missing sample_seq
    bad = '{"device_id":"pump-01","ts":"t","sensors":{"temperature":1,"vibration":1,"pressure":1,"humidity":1,"gas":1,"current":1}}'
    c.handle(FakeMsg("shtapm/pump-01/telemetry", bad))
    assert store.count == 0
    assert c.error_count == 1


def test_unexpected_sensor_field_rejected():
    c, store = _consumer()
    bad = _valid_payload().replace('"current":0.42', '"current":0.42,"flow":1.0')
    c.handle(FakeMsg("shtapm/pump-01/telemetry", bad))
    assert store.count == 0
    assert c.error_count == 1


def test_prd_shorthand_rejected():
    c, store = _consumer()
    bad = '{"device_id":"pump-01","ts":"t","sensors":{"temp":1,"vib":1,"pressure":1,"humidity":1,"gas":1,"current":1},"sample_seq":0}'
    c.handle(FakeMsg("shtapm/pump-01/telemetry", bad))
    assert store.count == 0
    assert c.error_count == 1


def test_wrong_topic_ignored():
    c, store = _consumer()
    c.handle(FakeMsg("shtapm/pump-01/decision", _valid_payload().encode()))
    assert store.count == 0
    assert c.error_count == 1


def test_topic_payload_device_mismatch_rejected():
    c, store = _consumer()
    # topic says pump-99, payload says pump-01
    c.handle(FakeMsg("shtapm/pump-99/telemetry", _valid_payload(device_id="pump-01").encode()))
    assert store.count == 0
    assert c.error_count == 1


def test_multiple_devices_ingested():
    c, store = _consumer()
    c.handle(FakeMsg("shtapm/pump-01/telemetry", _valid_payload("pump-01", 0).encode()))
    c.handle(FakeMsg("shtapm/pump-02/telemetry", _valid_payload("pump-02", 0).encode()))
    assert store.count == 2
    assert set(store.devices()) == {"pump-01", "pump-02"}
