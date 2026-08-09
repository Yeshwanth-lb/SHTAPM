"""M3.1 tests — publisher topic + payload serialization (fake client, no broker)."""

import json

from app.schemas.contracts import TelemetryMessage
from simulator.generator import TelemetrySimulator
from simulator.publisher import MqttTelemetryPublisher


class FakeClient:
    def __init__(self):
        self.calls = []

    def publish(self, topic, payload, qos=0):
        self.calls.append((topic, payload, qos))
        return None


def test_topic_matches_documented_pattern():
    pub = MqttTelemetryPublisher(FakeClient(), device_id="pump-01")
    assert pub.topic == "shtapm/pump-01/telemetry"


def test_publish_uses_topic_and_qos0():
    client = FakeClient()
    pub = MqttTelemetryPublisher(client, device_id="pump-07")
    pub.publish(TelemetrySimulator(seed=1).next("2026-08-09T12:00:00.000Z"))
    topic, payload, qos = client.calls[0]
    assert topic == "shtapm/pump-07/telemetry"
    assert qos == 0
    assert isinstance(payload, str)


def test_published_payload_is_frozen_contract_and_has_no_type():
    client = FakeClient()
    pub = MqttTelemetryPublisher(client, device_id="pump-01")
    pub.publish(TelemetrySimulator(seed=5).next("2026-08-09T12:00:00.000Z"))
    _, payload, _ = client.calls[0]
    data = json.loads(payload)
    # MQTT payload carries no WS envelope "type" (ruling E)
    assert "type" not in data
    # payload validates against the canonical contract
    TelemetryMessage.model_validate(data)
    assert set(data.keys()) == {"device_id", "ts", "sensors", "sample_seq"}
