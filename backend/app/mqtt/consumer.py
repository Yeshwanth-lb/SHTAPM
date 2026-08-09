"""Backend MQTT telemetry consumer (P0 M3.3).

Subscribes to ``shtapm/+/telemetry``, decodes JSON, validates against the frozen
M2 contract (``TelemetryMessage``), and writes valid messages into the in-memory
``TelemetryStore``. Malformed JSON, contract violations, and topic/payload
device mismatches are logged and counted — never allowed to crash the consumer.

paho-mqtt runs its network loop on a background thread (``loop_start``), so
ingestion is non-blocking to the FastAPI event loop. paho is imported lazily in
``start`` so unit tests of ``handle`` need neither paho nor a broker.

No persistence, no WebSockets, no decision/ledger handling — those are later.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.schemas.contracts import TelemetryMessage
from app.services.telemetry_store import TelemetryStore

# A sink receives each VALIDATED telemetry message (e.g. the WS broadcaster).
TelemetrySink = Callable[[TelemetryMessage], None]

log = logging.getLogger("shtapm.mqtt")

TELEMETRY_SUBSCRIPTION = "shtapm/+/telemetry"


def device_from_topic(topic: str) -> str | None:
    """Return device_id for ``shtapm/<device_id>/telemetry`` topics, else None."""
    parts = topic.split("/")
    if len(parts) == 3 and parts[0] == "shtapm" and parts[2] == "telemetry":
        return parts[1]
    return None


class TelemetryConsumer:
    def __init__(self, store: TelemetryStore) -> None:
        self.store = store
        self._client: Any | None = None
        self.subscription = TELEMETRY_SUBSCRIPTION
        self.error_count = 0
        self._sinks: list[TelemetrySink] = []

    def add_sink(self, sink: TelemetrySink) -> None:
        """Register a downstream consumer of validated telemetry (e.g. WS fan-out).

        Keeps ingestion decoupled from the WS layer: the consumer knows only
        'sinks', so the WS broadcaster (or a P4 replacement) can be wired in
        without changing this class.
        """
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
            message = TelemetryMessage.model_validate_json(payload)
        except Exception as exc:  # malformed JSON or contract violation
            self._reject(topic, f"invalid telemetry: {type(exc).__name__}")
            return
        if message.device_id != topic_device:
            self._reject(
                topic, f"topic/payload device mismatch ({topic_device} != {message.device_id})"
            )
            return
        self.store.update(message)
        for sink in self._sinks:
            try:
                sink(message)
            except Exception:  # a sink failure must not break ingestion
                log.warning("telemetry sink error", exc_info=False)

    def _reject(self, topic: str, reason: str) -> None:
        self.error_count += 1
        # log topic + reason only — never the raw payload
        log.warning("rejected message on %s: %s", topic, reason)

    # ---- lifecycle (real broker) --------------------------------------------
    def start(self, host: str, port: int) -> None:
        import paho.mqtt.client as mqtt  # lazy: unit tests need no paho

        client = mqtt.Client()
        self.attach(client)
        client.connect_async(host, port)  # non-blocking; retries if broker down
        client.loop_start()

    def stop(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()

    def is_connected(self) -> bool:
        return bool(self._client is not None and self._client.is_connected())
