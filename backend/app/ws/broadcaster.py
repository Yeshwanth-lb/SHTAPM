"""Telemetry broadcaster — the seam between MQTT ingestion and WS clients (M3.4).

The MQTT consumer runs on paho's network thread; WebSocket clients live on the
asyncio event loop. This in-memory pub/sub bridges the two: ``publish_from_thread``
is called from the paho thread and hands each frame to the loop via
``call_soon_threadsafe``; each connected client holds a bounded asyncio queue.

Deliberately small so P4 can replace it with a production gateway (e.g. a
Redis-backed fan-out) without touching the MQTT consumer or the WS route — both
depend only on ``publish_from_thread`` / ``subscribe`` / ``unsubscribe``.

NOT a durable event stream: bounded per-client queues drop frames for a slow
client rather than block the loop or grow without limit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.schemas.contracts import TelemetryMessage
from app.ws.frames import telemetry_frame

log = logging.getLogger("shtapm.ws")


class TelemetryBroadcaster:
    def __init__(self, loop: asyncio.AbstractEventLoop, queue_maxsize: int = 100) -> None:
        self._loop = loop
        self._subscribers: set[asyncio.Queue] = set()
        self._maxsize = queue_maxsize

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    @property
    def client_count(self) -> int:
        return len(self._subscribers)

    def publish_from_thread(self, message: TelemetryMessage) -> None:
        """Called from the paho network thread; schedule delivery on the loop."""
        frame = telemetry_frame(message)
        self._loop.call_soon_threadsafe(self._deliver, frame)

    def _deliver(self, frame: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                log.warning("ws client queue full; dropping telemetry frame")
