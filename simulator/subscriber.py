"""MQTT telemetry subscriber / verifier — collects and validates telemetry.

Used by the M3.2 round-trip harness and integration test to prove that what the
simulator published to Mosquitto arrives intact and validates against the frozen
contract (backend/app/schemas/contracts.py). No business logic.

The paho client is injected and wired via callbacks. The message handler is
duck-typed on the paho ``MQTTMessage`` (``.topic``, ``.payload``), so it is
unit-testable with a fake message and needs neither paho nor a broker.
"""

from __future__ import annotations

from typing import Any

from app.schemas.contracts import TelemetryMessage

from simulator.publisher import TELEMETRY_TOPIC


class MqttTelemetrySubscriber:
    def __init__(self, client: Any, device_id: str = "pump-01") -> None:
        self._client = client
        self.device_id = device_id
        self.topic = TELEMETRY_TOPIC.format(device_id=device_id)
        self.messages: list[TelemetryMessage] = []
        self.errors: list[str] = []
        client.on_connect = self._on_connect
        client.on_message = self._on_message

    # paho 1.6 callback signatures
    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        client.subscribe(self.topic, qos=0)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        self.handle(msg)

    def handle(self, msg: Any) -> None:
        """Validate one message; append to messages, or record the error."""
        try:
            payload = msg.payload
            if isinstance(payload, bytes | bytearray):
                payload = payload.decode("utf-8")
            self.messages.append(TelemetryMessage.model_validate_json(payload))
        except Exception as exc:  # invalid JSON or contract violation
            self.errors.append(str(exc))
