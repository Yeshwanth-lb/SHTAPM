"""Backend consumer for the edge's retained relay status (D041).

Subscribes to ``shtapm/+/actuation`` (QoS 1). Each valid ``ActuationStatus``
goes to every sink -- the in-memory registry the REST API reads, and the
ledger recorder. Invalid payloads and topic/device mismatches are rejected and
counted, never coerced: a wrong "relay on" is worse than no update.

Retained messages are the point: a backend that restarts learns the relay's
current state on subscribe. Its own client and thread, independent of every
other consumer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.schemas.actuation import (
    ACTUATION_SUBSCRIPTION,
    ActuationStatus,
    device_from_actuation_topic,
    parse_actuation_status,
)

log = logging.getLogger("shtapm.mqtt.actuation")

ActuationSink = Callable[[ActuationStatus], None]


class ActuationConsumer:
    def __init__(self) -> None:
        self._client: Any | None = None
        self.subscription = ACTUATION_SUBSCRIPTION
        self.error_count = 0
        self._sinks: list[ActuationSink] = []

    def add_sink(self, sink: ActuationSink) -> None:
        self._sinks.append(sink)

    def attach(self, client: Any) -> None:
        self._client = client
        client.on_connect = self._on_connect
        client.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        client.subscribe(self.subscription, qos=1)
        log.info("mqtt connected; subscribed to %s", self.subscription)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        self.handle(msg)

    def handle(self, msg: Any) -> None:
        topic = getattr(msg, "topic", "")
        device_id = device_from_actuation_topic(topic)
        if device_id is None:
            self._reject(topic, "unrecognized topic")
            return
        try:
            status = parse_actuation_status(getattr(msg, "payload", b""))
        except Exception as e:
            self._reject(topic, f"invalid actuation status: {type(e).__name__}")
            return
        if status.device_id != device_id:
            self._reject(topic, f"topic/payload device mismatch ({device_id})")
            return
        for sink in self._sinks:
            try:
                sink(status)
            except Exception:
                log.warning("actuation sink error", exc_info=False)

    def _reject(self, topic: str, reason: str) -> None:
        self.error_count += 1
        log.warning("rejected actuation message on %s: %s", topic, reason)

    def start(self, host: str, port: int) -> None:
        try:
            import paho.mqtt.client as mqtt  # lazy: unit tests need no paho

            client = mqtt.Client()
            self.attach(client)
            client.connect_async(host, port)
            client.loop_start()
        except Exception:
            log.warning("actuation consumer failed to start; relay state unavailable")
            self._client = None

    def stop(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            log.debug("actuation consumer did not stop cleanly", exc_info=False)
