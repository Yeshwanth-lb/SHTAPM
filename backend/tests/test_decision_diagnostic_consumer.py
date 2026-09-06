"""Backend decision_diagnostic consumer tests (no paho, no broker) -- mirrors
test_mqtt_consumer.py's own pattern exactly, for the new, separate
shtapm/{device_id}/decision_diagnostic topic/schema."""

from __future__ import annotations

from app.mqtt.decision_diagnostic_consumer import DecisionDiagnosticConsumer, device_from_topic


class FakeMsg:
    def __init__(self, topic: str, payload):
        self.topic = topic
        self.payload = payload


def _valid_payload(device_id="pump-01", seq=0) -> str:
    return (
        '{"device_id":"%s","ts":"2026-09-06T12:00:00.000Z","sample_seq":%d,'
        '"window_start_index":0,"window_end_index":30,'
        '"anomaly_flag":false,"anomaly_severity":0.0,'
        '"trust":{"temperature":0.9,"vibration":0.9,"pressure":0.9,'
        '"humidity":0.9,"gas":0.9,"current":0.9},'
        '"attribution":{'
        '"temperature":{"attribution":"none","reason":""},'
        '"vibration":{"attribution":"none","reason":""},'
        '"pressure":{"attribution":"none","reason":""},'
        '"humidity":{"attribution":"none","reason":""},'
        '"gas":{"attribution":"none","reason":""},'
        '"current":{"attribution":"none","reason":""}},'
        '"isolation_candidates":[],"tracked_isolation_candidates":[]}' % (device_id, seq)
    )


def _consumer():
    return DecisionDiagnosticConsumer()


def test_device_from_topic():
    assert device_from_topic("shtapm/pump-01/decision_diagnostic") == "pump-01"
    assert device_from_topic("shtapm/pump-01/telemetry") is None
    assert device_from_topic("shtapm/pump-01/decision") is None
    assert device_from_topic("garbage") is None


def test_valid_message_reaches_sink():
    c = _consumer()
    received = []
    c.add_sink(received.append)
    c.handle(FakeMsg("shtapm/pump-01/decision_diagnostic", _valid_payload().encode()))
    assert len(received) == 1
    assert received[0].device_id == "pump-01"
    assert c.error_count == 0


def test_malformed_json_handled_safely():
    c = _consumer()
    received = []
    c.add_sink(received.append)
    c.handle(FakeMsg("shtapm/pump-01/decision_diagnostic", b"not-json{"))
    assert received == []
    assert c.error_count == 1  # counted, not crashed


def test_schema_invalid_rejected():
    c = _consumer()
    received = []
    c.add_sink(received.append)
    bad = _valid_payload().replace(
        '"anomaly_flag":false', '"anomaly_flag":false,"health":"healthy"'
    )
    c.handle(FakeMsg("shtapm/pump-01/decision_diagnostic", bad))
    assert received == []
    assert c.error_count == 1


def test_missing_required_field_rejected():
    c = _consumer()
    received = []
    c.add_sink(received.append)
    bad = '{"device_id":"pump-01","ts":"t"}'
    c.handle(FakeMsg("shtapm/pump-01/decision_diagnostic", bad))
    assert received == []
    assert c.error_count == 1


def test_wrong_topic_ignored():
    c = _consumer()
    received = []
    c.add_sink(received.append)
    c.handle(FakeMsg("shtapm/pump-01/telemetry", _valid_payload().encode()))
    assert received == []
    assert c.error_count == 1


def test_topic_payload_device_mismatch_rejected():
    c = _consumer()
    received = []
    c.add_sink(received.append)
    c.handle(
        FakeMsg(
            "shtapm/pump-99/decision_diagnostic", _valid_payload(device_id="pump-01").encode()
        )
    )
    assert received == []
    assert c.error_count == 1


def test_multiple_devices_ingested():
    c = _consumer()
    received = []
    c.add_sink(received.append)
    c.handle(FakeMsg("shtapm/pump-01/decision_diagnostic", _valid_payload("pump-01", 0).encode()))
    c.handle(FakeMsg("shtapm/pump-02/decision_diagnostic", _valid_payload("pump-02", 0).encode()))
    assert {m.device_id for m in received} == {"pump-01", "pump-02"}


def test_sink_failure_does_not_break_ingestion_or_other_sinks():
    c = _consumer()

    def _broken_sink(message):
        raise RuntimeError("db is on fire")

    received = []
    c.add_sink(_broken_sink)
    c.add_sink(received.append)
    c.handle(FakeMsg("shtapm/pump-01/decision_diagnostic", _valid_payload().encode()))
    assert len(received) == 1  # second sink still received it despite the first raising
