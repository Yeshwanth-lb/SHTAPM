"""MQTT telemetry publisher — thin wrapper (no business logic).

Publishes the frozen telemetry message to the documented topic
``shtapm/{device_id}/telemetry`` at QoS 0 (TRD §02.3). The MQTT client is
injected so this module has no hard paho-mqtt dependency and stays unit-testable
with a fake client (the real paho client is built in ``__main__``).

The published payload is the canonical MQTT payload (no ``type`` field — ruling
E); the WebSocket ``type`` envelope is a backend concern (M3.2+).
"""

from __future__ import annotations

from typing import Protocol

from app.schemas.contracts import TelemetryMessage

TELEMETRY_TOPIC = "shtapm/{device_id}/telemetry"


class MqttClient(Protocol):
    def publish(self, topic: str, payload: str, qos: int = 0) -> object: ...


class MqttTelemetryPublisher:
    def __init__(self, client: MqttClient, device_id: str = "pump-01") -> None:
        self._client = client
        self.device_id = device_id

    @property
    def topic(self) -> str:
        return TELEMETRY_TOPIC.format(device_id=self.device_id)

    def publish(self, message: TelemetryMessage) -> None:
        # model_dump_json emits exactly the frozen fields (no type on MQTT).
        self._client.publish(self.topic, message.model_dump_json(), qos=0)
