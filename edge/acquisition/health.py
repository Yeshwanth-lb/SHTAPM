"""Which sensors are dead right now, and since when (D045).

Updated once per acquisition tick from the sampler's per-channel health. Read
by the safety supervisor (a dead current sensor blinds dry-run protection) and
by the decision publisher (``stale_channels`` -> dashboard "SENSOR DEAD").
Transitions are logged once, not every tick. Thread-safe.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from edge.acquisition.sampler import SampleResult

log = logging.getLogger("shtapm.edge.channel_health")


class ChannelHealthBoard:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._since: dict[str, float] = {}
        self._lock = threading.Lock()

    def update(self, result: SampleResult) -> None:
        unhealthy = {ch for ch, reading in result.readings.items() if not reading.healthy}
        now = self._clock()
        with self._lock:
            for ch in sorted(unhealthy - set(self._since)):
                self._since[ch] = now
                held = "holding its last good value" if ch in result.stale else "no value to hold"
                log.warning("SENSOR DEAD: %s stopped responding (%s)", ch, held)
            for ch in sorted(set(self._since) - unhealthy):
                del self._since[ch]
                log.warning("sensor recovered: %s is responding again", ch)

    def stale(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._since)

    def dead_for(self, channel: str) -> float | None:
        """Seconds since ``channel`` stopped responding, or None if healthy."""
        with self._lock:
            since = self._since.get(channel)
        return None if since is None else self._clock() - since
