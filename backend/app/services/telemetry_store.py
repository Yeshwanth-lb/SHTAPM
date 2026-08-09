"""In-memory validated-telemetry store (P0 M3.3).

Holds the latest validated ``TelemetryMessage`` per device plus a running count,
so M3.4 (WebSocket fan-out) can read live state without changing the ingestion
layer. Thread-safe: the MQTT consumer writes from paho's network thread.

NOT a database. No persistence, no history retention — that is P4.
"""

from __future__ import annotations

from threading import Lock

from app.schemas.contracts import TelemetryMessage


class TelemetryStore:
    def __init__(self) -> None:
        self._latest: dict[str, TelemetryMessage] = {}
        self._count = 0
        self._lock = Lock()

    def update(self, message: TelemetryMessage) -> None:
        with self._lock:
            self._latest[message.device_id] = message
            self._count += 1

    def latest(self, device_id: str) -> TelemetryMessage | None:
        with self._lock:
            return self._latest.get(device_id)

    def all_latest(self) -> dict[str, TelemetryMessage]:
        with self._lock:
            return dict(self._latest)

    def devices(self) -> list[str]:
        with self._lock:
            return list(self._latest.keys())

    @property
    def count(self) -> int:
        with self._lock:
            return self._count
