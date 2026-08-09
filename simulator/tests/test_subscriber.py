"""M3.2 unit tests — subscriber validation logic (no broker, no paho)."""

from app.schemas.contracts import TelemetryMessage

from simulator.generator import TelemetrySimulator
from simulator.publisher import MqttTelemetryPublisher
from simulator.subscriber import MqttTelemetrySubscriber


class FakeClient:
    """Minimal stand-in: records callbacks + captures publishes."""

    def __init__(self):
        self.on_connect = None
        self.on_message = None
        self.subscribed = []
        self.published = []

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))


class FakeMsg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


def _valid_payload(device_id="pump-01"):
    client = FakeClient()
    MqttTelemetryPublisher(client, device_id=device_id).publish(
        TelemetrySimulator(seed=1, device_id=device_id).next("2026-08-09T12:00:00.000Z")
    )
    return client.published[0][1]  # the serialized JSON string


def test_on_connect_subscribes_to_topic():
    client = FakeClient()
    sub = MqttTelemetrySubscriber(client, device_id="pump-01")
    client.on_connect(client, None, None, 0)
    assert client.subscribed == [("shtapm/pump-01/telemetry", 0)]
    assert sub.topic == "shtapm/pump-01/telemetry"


def test_valid_message_collected_and_validated():
    client = FakeClient()
    sub = MqttTelemetrySubscriber(client, device_id="pump-01")
    sub.handle(FakeMsg("shtapm/pump-01/telemetry", _valid_payload().encode()))
    assert len(sub.messages) == 1
    assert isinstance(sub.messages[0], TelemetryMessage)
    assert sub.errors == []


def test_invalid_json_recorded_as_error_not_crash():
    client = FakeClient()
    sub = MqttTelemetrySubscriber(client, device_id="pump-01")
    sub.handle(FakeMsg("shtapm/pump-01/telemetry", b"not-json"))
    assert sub.messages == []
    assert len(sub.errors) == 1


def test_contract_violation_recorded_as_error():
    client = FakeClient()
    sub = MqttTelemetrySubscriber(client, device_id="pump-01")
    # PRD shorthand "temp"/"vib" must be rejected by the frozen contract
    bad = (
        '{"device_id":"pump-01","ts":"t","sensors":'
        '{"temp":1,"vib":1,"pressure":1,"humidity":1,"gas":1,"current":1},"sample_seq":0}'
    )
    sub.handle(FakeMsg("shtapm/pump-01/telemetry", bad))
    assert sub.messages == []
    assert len(sub.errors) == 1
