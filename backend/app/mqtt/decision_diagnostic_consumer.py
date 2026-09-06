"""Backend MQTT decision-diagnostic consumer.

Subscribes to ``shtapm/+/decision_diagnostic`` (a NEW, separate topic — see
``app.schemas.decision_diagnostic``'s own docstring for why this is not the
frozen Doc05 ``.../decision`` topic/``DecisionMessage`` shape), decodes
JSON, validates against ``DecisionDiagnosticMessage``, and hands each valid
message to registered sinks. Malformed JSON, schema violations, and topic/
payload device mismatches are logged and counted — never allowed to crash
the consumer, mirroring ``app.mqtt.consumer.TelemetryConsumer`` exactly.

Wholly independent of ``TelemetryConsumer``: its own client, its own
subscription, its own thread. A broker that rejects or never delivers this
topic — or a bug anywhere in this consumer — cannot affect telemetry
ingestion, which neither imports nor calls into this module.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from app.schemas.decision_diagnostic import DecisionDiagnosticMessage

# A sink receives each VALIDATED decision-diagnostic message.
DecisionDiagnosticSink = Callable[[DecisionDiagnosticMessage], None]

log = logging.getLogger("shtapm.mqtt.decision_diagnostic")

DECISION_DIAGNOSTIC_SUBSCRIPTION = "shtapm/+/decision_diagnostic"


def device_from_topic(topic: str) -> str | None:
    """Return device_id for ``shtapm/<device_id>/decision_diagnostic``, else None."""
    parts = topic.split("/")
    if len(parts) == 3 and parts[0] == "shtapm" and parts[2] == "decision_diagnostic":
        return parts[1]
    return None


class DecisionDiagnosticConsumer:
    def __init__(self) -> None:
        self._client: Any | None = None
        self._thread: threading.Thread | None = None
        self.subscription = DECISION_DIAGNOSTIC_SUBSCRIPTION
        self.error_count = 0
        self._sinks: list[DecisionDiagnosticSink] = []

    def add_sink(self, sink: DecisionDiagnosticSink) -> None:
        """Register a downstream consumer of validated diagnostic messages
        (e.g. the persistence sink). Keeps ingestion decoupled, same seam
        shape as ``TelemetryConsumer.add_sink``."""
        self._sinks.append(sink)

    # ---- wiring (paho callbacks; safe to attach to a fake client in tests) ---
    def attach(self, client: Any) -> None:
        self._client = client
        client.on_connect = self._on_connect
        client.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        client.subscribe(self.subscription, qos=0)
        log.info("mqtt connected; subscribed to %s", self.subscription)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        self.handle(msg)

    # ---- message handling (unit-testable without paho/broker) ----------------
    def handle(self, msg: Any) -> None:
        topic = getattr(msg, "topic", "")
        topic_device = device_from_topic(topic)
        if topic_device is None:
            self._reject(topic, "unrecognized topic")
            return
        try:
            payload = msg.payload
            if isinstance(payload, bytes | bytearray):
                payload = payload.decode("utf-8")
            message = DecisionDiagnosticMessage.model_validate_json(payload)
        except Exception as exc:  # malformed JSON or schema violation
            self._reject(topic, f"invalid decision_diagnostic: {type(exc).__name__}")
            return
        if message.device_id != topic_device:
            self._reject(
                topic, f"topic/payload device mismatch ({topic_device} != {message.device_id})"
            )
            return
        for sink in self._sinks:
            try:
                sink(message)
            except Exception:  # a sink failure must not break ingestion
                log.warning("decision_diagnostic sink error", exc_info=False)

    def _reject(self, topic: str, reason: str) -> None:
        self.error_count += 1
        # log topic + reason only — never the raw payload
        log.warning("rejected message on %s: %s", topic, reason)

    # ---- lifecycle (real broker) --------------------------------------------
    def start(self, host: str, port: int) -> None:
        import paho.mqtt.client as mqtt  # lazy: unit tests need no paho

        client = mqtt.Client()
        self.attach(client)
        client.connect_async(host, port)  # non-blocking; resolves in the loop
        self._thread = threading.Thread(
            target=client.loop_forever,
            kwargs={"retry_first_connection": True},
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._client is not None:
            self._client.disconnect()  # breaks loop_forever
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def is_connected(self) -> bool:
        return bool(self._client is not None and self._client.is_connected())
