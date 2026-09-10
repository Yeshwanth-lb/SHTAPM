"""Backend MQTT device-status consumer.

Subscribes to ``shtapm/+/status`` and records the edge publisher's retained
Last-Will state into ``devices.status``.

WHY THIS EXISTS: the edge has always published this
(``edge/acquisition/mqtt_publisher.py`` — ``will_set(.../status, "offline",
retain=True)`` armed before connect, retained ``"online"`` on connect, retained
``"offline"`` on graceful stop), but nothing subscribed. ``devices.status``
therefore sat at its schema default ``offline`` forever while telemetry was
visibly arriving, so the fleet view stated a falsehood about a running pump.

The payload is the plain string ``"online"``/``"offline"`` — NOT JSON, and not
the frozen telemetry contract. Anything else is rejected and counted; an
unrecognised payload must never be coerced into a status, because a wrong
"online" is worse than no update at all.

Wholly independent of ``TelemetryConsumer`` and ``DecisionDiagnosticConsumer``:
its own client, subscription and thread. A failure here cannot affect telemetry
ingestion, which does not import this module.

RETAINED MESSAGES ARE THE POINT. Because the edge publishes with
``retain=True``, a backend that restarts receives the device's current status
immediately on subscribe, rather than staying wrong until the next transition.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

# A sink receives (device_id, status) for each VALID status message.
StatusSink = Callable[[str, str], None]

log = logging.getLogger("shtapm.mqtt.status")

STATUS_SUBSCRIPTION = "shtapm/+/status"

# The only two payloads the edge publisher emits (mqtt_publisher.py's
# STATUS_ONLINE / STATUS_OFFLINE). Kept as plain strings deliberately: this is
# not the frozen contract and gains nothing from a schema.
ONLINE = "online"
OFFLINE = "offline"
_VALID_STATUSES = frozenset({ONLINE, OFFLINE})


def device_from_topic(topic: str) -> str | None:
    """Return device_id for ``shtapm/<device_id>/status``, else None."""
    parts = topic.split("/")
    if len(parts) == 3 and parts[0] == "shtapm" and parts[2] == "status":
        return parts[1]
    return None


class StatusConsumer:
    def __init__(self) -> None:
        self._client: Any | None = None
        self._thread: threading.Thread | None = None
        self.subscription = STATUS_SUBSCRIPTION
        self.error_count = 0
        self._sinks: list[StatusSink] = []

    def add_sink(self, sink: StatusSink) -> None:
        self._sinks.append(sink)

    # ---- wiring (paho callbacks; safe to attach to a fake client in tests) ---
    def attach(self, client: Any) -> None:
        self._client = client
        client.on_connect = self._on_connect
        client.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        # qos=1 matches the publisher's own QoS for status (mqtt_publisher.py),
        # so a transition is not silently dropped the way a qos=0 telemetry
        # frame acceptably can be.
        client.subscribe(self.subscription, qos=1)
        log.info("mqtt connected; subscribed to %s", self.subscription)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        self.handle(msg)

    # ---- message handling (unit-testable without paho/broker) ----------------
    def handle(self, msg: Any) -> None:
        topic = getattr(msg, "topic", "")
        device_id = device_from_topic(topic)
        if device_id is None:
            self._reject(topic, "unrecognized topic")
            return

        payload = getattr(msg, "payload", b"")
        if isinstance(payload, bytes | bytearray):
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError:
                self._reject(topic, "undecodable payload")
                return
        status = str(payload).strip().lower()

        if status not in _VALID_STATUSES:
            # Never guess. An unrecognised payload leaves the stored status
            # untouched rather than defaulting either way.
            self._reject(topic, "unrecognized status payload")
            return

        for sink in self._sinks:
            try:
                sink(device_id, status)
            except Exception:  # a sink failure must not break ingestion
                log.warning("status sink error", exc_info=False)

    def _reject(self, topic: str, reason: str) -> None:
        self.error_count += 1
        # log topic + reason only — never the raw payload
        log.warning("rejected status message on %s: %s", topic, reason)

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
