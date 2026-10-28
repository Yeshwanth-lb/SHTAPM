"""Which sensors are dead right now, and since when (D045, debounced D047).

Updated once per acquisition tick from the sampler's per-channel health. Read
by the safety supervisor (a dead current sensor blinds dry-run protection) and
by the decision publisher (``stale_channels`` -> dashboard "SENSOR DEAD").

DEBOUNCE (D047). A channel is reported dead only after it has failed
continuously for ``dead_after_s`` (default 5 s). The DHT22 misses a read for
2-3 s whenever the motor starts (measured 2026-10-28: two blips, recovered on
their own); reporting each blip flashed "SENSOR DEAD" on every switch-on. The
sampler still holds the last good value from the first failed read -- only the
REPORT waits. Transitions are logged once, not every tick. Thread-safe.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from edge.acquisition.sampler import SampleResult

log = logging.getLogger("shtapm.edge.channel_health")

DEAD_AFTER_S = 5.0


class ChannelHealthBoard:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        dead_after_s: float = DEAD_AFTER_S,
    ) -> None:
        self._clock = clock
        self._dead_after_s = dead_after_s
        self._failing_since: dict[str, float] = {}
        self._dead: set[str] = set()
        self._lock = threading.Lock()

    def update(self, result: SampleResult) -> None:
        unhealthy = {ch for ch, reading in result.readings.items() if not reading.healthy}
        now = self._clock()
        with self._lock:
            for ch in unhealthy:
                self._failing_since.setdefault(ch, now)
            for ch in sorted(unhealthy - self._dead):
                if now - self._failing_since[ch] >= self._dead_after_s:
                    self._dead.add(ch)
                    held = (
                        "holding its last good value" if ch in result.stale else "no value to hold"
                    )
                    log.warning("SENSOR DEAD: %s stopped responding (%s)", ch, held)
            for ch in sorted(set(self._failing_since) - unhealthy):
                del self._failing_since[ch]
                if ch in self._dead:
                    self._dead.discard(ch)
                    log.warning("sensor recovered: %s is responding again", ch)

    def stale(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._dead)

    def dead_for(self, channel: str) -> float | None:
        """Seconds since ``channel`` started failing, once it is reported dead."""
        with self._lock:
            if channel not in self._dead:
                return None
            since = self._failing_since[channel]
        return self._clock() - since
