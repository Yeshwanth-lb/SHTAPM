"""Resilient edge MQTT telemetry publisher (P1 · C3 · FR-Q4).

Consumes C2 ``TelemetryMessage`` frames and publishes them to
``shtapm/{device_id}/telemetry`` at QoS 0. Adds the FR-Q4 resilience the thin
simulator publisher lacks:

- **LWT:** ``will_set(shtapm/{device_id}/status, "offline", qos=1, retain=True)``
  so the broker marks the device offline on an ungraceful drop.
- **online on connect:** publishes retained ``"online"`` (QoS 1) on (re)connect.
- **graceful stop:** publishes retained ``"offline"`` then disconnects.
- **buffered resume (FR-Q4):** while disconnected, frames go into a bounded ring
  sized ``ceil(rate_hz * retention_seconds)`` (default 60 s → no loss for ≥60 s at
  the configured rate). On reconnect the buffer is **drained FIFO (oldest→newest)
  before** any new live frame, preserving ``sample_seq`` order.
- **bounded memory:** past the retention window the oldest frames are overwritten
  (C2 ``RingBuffer`` semantics) — no unbounded growth, no backpressure (decision B).
- **reconnect:** paho ``reconnect_delay_set`` with configurable bounds (decision D).

Status payload is the plain string ``"online"``/``"offline"`` (decision A). No
change to the frozen telemetry contract; topic strings are edge-local (decision
E — no shared-package consolidation here).
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any

from app.schemas.contracts import TelemetryMessage

from edge.acquisition.ring_buffer import RingBuffer
from edge.acquisition.sampler import MAX_RATE_HZ, MIN_RATE_HZ

log = logging.getLogger("shtapm.edge.publisher")

TELEMETRY_TOPIC = "shtapm/{device_id}/telemetry"
STATUS_TOPIC = "shtapm/{device_id}/status"
STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"

DEFAULT_RETENTION_SECONDS = 60
DEFAULT_RECONNECT_MIN_DELAY = 1.0
DEFAULT_RECONNECT_MAX_DELAY = 30.0


def buffer_capacity(rate_hz: float, retention_seconds: float = DEFAULT_RETENTION_SECONDS) -> int:
    """FR-Q4 resume-buffer capacity = ceil(rate_hz * retention_seconds)."""
    return math.ceil(rate_hz * retention_seconds)


class ResilientTelemetryPublisher:
    def __init__(
        self,
        *,
        device_id: str,
        rate_hz: float,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
        reconnect_min_delay: float = DEFAULT_RECONNECT_MIN_DELAY,
        reconnect_max_delay: float = DEFAULT_RECONNECT_MAX_DELAY,
        client: Any | None = None,
    ) -> None:
        if not (MIN_RATE_HZ <= rate_hz <= MAX_RATE_HZ):
            raise ValueError(f"rate_hz must be in [{MIN_RATE_HZ}, {MAX_RATE_HZ}], got {rate_hz}")
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be > 0")
        self.device_id = device_id
        self.telemetry_topic = TELEMETRY_TOPIC.format(device_id=device_id)
        self.status_topic = STATUS_TOPIC.format(device_id=device_id)
        self._rc_min = reconnect_min_delay
        self._rc_max = reconnect_max_delay
        self.buffer: RingBuffer[TelemetryMessage] = RingBuffer(
            buffer_capacity(rate_hz, retention_seconds)
        )
        self._connected = False
        self._client: Any | None = None
        self._thread: threading.Thread | None = None
        if client is not None:
            self.attach(client)

    # ---- wiring -------------------------------------------------------------
    def attach(self, client: Any) -> None:
        """Wire callbacks + arm the Last Will (offline) BEFORE connecting."""
        self._client = client
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.will_set(self.status_topic, STATUS_OFFLINE, qos=1, retain=True)

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any) -> None:
        self._connected = True
        client.publish(self.status_topic, STATUS_ONLINE, qos=1, retain=True)
        log.info(
            "connected; published retained status=online; draining %d buffered", len(self.buffer)
        )
        self._drain()

    def _on_disconnect(self, client: Any, userdata: Any, rc: Any) -> None:
        self._connected = False
        log.warning("disconnected; buffering telemetry (rc=%s)", rc)

    # ---- publish path -------------------------------------------------------
    def publish(self, message: TelemetryMessage) -> None:
        """Live-publish when connected + buffer empty; otherwise buffer. If
        connected with a non-empty backlog, append then drain so buffered frames
        always precede this one (FIFO ordering preserved)."""
        if self._connected and len(self.buffer) == 0:
            self._publish_live(message)
        elif self._connected:
            self.buffer.append(message)
            self._drain()
        else:
            self.buffer.append(message)  # bounded; overwrites oldest past window

    def _publish_live(self, message: TelemetryMessage) -> None:
        self._client.publish(self.telemetry_topic, message.model_dump_json(), qos=0)

    def _drain(self) -> None:
        pending = self.buffer.snapshot()  # oldest → newest
        self.buffer.clear()
        for message in pending:
            self._publish_live(message)

    # ---- lifecycle ----------------------------------------------------------
    def start(self, host: str, port: int) -> None:
        import paho.mqtt.client as mqtt

        client = mqtt.Client()
        client.reconnect_delay_set(min_delay=self._rc_min, max_delay=self._rc_max)
        self.attach(client)
        client.connect_async(host, port)
        self._thread = threading.Thread(
            target=client.loop_forever, kwargs={"retry_first_connection": True}, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Graceful: publish retained offline, then disconnect + join loop."""
        if self._client is not None:
            try:
                self._client.publish(self.status_topic, STATUS_OFFLINE, qos=1, retain=True)
            except Exception:
                log.warning("failed to publish offline status on stop", exc_info=False)
            self._client.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected
