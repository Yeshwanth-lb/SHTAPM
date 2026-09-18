"""Measure edge-publish -> backend-receipt latency from the live stream.

``GET /api/system/health`` reported ``e2e_latency_ms: null`` because nothing in
the running backend measured latency; the only figure this project ever had came
from a one-off hardware-free script. This supplies a real one.

WHAT IS MEASURED, PRECISELY: the interval between the timestamp the edge stamped
on a frame (``TelemetryMessage.ts``, set at sampling time) and the moment the
backend's MQTT consumer received it. That covers sampling -> publish -> broker ->
network -> ingest.

WHAT IS NOT MEASURED: rendering. PRD NFR-P1/AC6 asks for sensor -> UI under 2 s,
and the browser leg is not included here. Reporting this number as "sensor to UI"
would understate the real figure, so it is named and documented as
edge -> backend throughout.

CLOCK SKEW IS A REAL HAZARD, NOT A THEORETICAL ONE: the edge and backend are
different machines, so this measurement is only as good as their clock
agreement. A skewed clock produces a systematically wrong figure, and a
sufficiently skewed one produces NEGATIVE latency. Negative samples are
therefore rejected and counted rather than clamped to zero: a clamp would
silently turn "the clocks disagree" into a plausible-looking 0 ms. When negative
samples are present the reported latency is withheld entirely -- a null that
says "cannot measure" is more useful than a number that cannot be trusted.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

# Enough to cover several minutes at 1 Hz without unbounded growth. A rolling
# window also means a transient stall ages out instead of skewing the figure
# forever.
DEFAULT_WINDOW = 300


@dataclass(frozen=True)
class LatencySnapshot:
    """``None`` percentiles mean "not measurable", never "zero"."""

    samples: int
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None
    negative_samples: int
    clock_skew_suspected: bool


class LatencyTracker:
    """Rolling edge->backend latency, safe to call from the MQTT thread."""

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        self._samples: deque[float] = deque(maxlen=window)
        self._negative = 0
        # The MQTT consumer runs on paho's thread while the API reads from a
        # request thread, so the deque and counter need guarding.
        self._lock = threading.Lock()

    def record(self, frame_ts: str, received_at: datetime | None = None) -> None:
        """Record one frame's latency. Never raises: a malformed timestamp must
        not break telemetry ingestion, which is this sink's only caller."""
        try:
            published = datetime.fromisoformat(frame_ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return
        now = received_at or datetime.now(UTC)
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        delta_ms = (now - published).total_seconds() * 1000.0

        with self._lock:
            if delta_ms < 0:
                # Impossible unless the clocks disagree. Counted, never clamped.
                self._negative += 1
                return
            self._samples.append(delta_ms)

    def snapshot(self) -> LatencySnapshot:
        with self._lock:
            samples = sorted(self._samples)
            negative = self._negative

        if negative:
            # Some frames appear to arrive before they were sent. Any figure
            # derived from the same clock pair is untrustworthy, so report none.
            return LatencySnapshot(
                samples=len(samples),
                p50_ms=None,
                p95_ms=None,
                max_ms=None,
                negative_samples=negative,
                clock_skew_suspected=True,
            )
        if not samples:
            return LatencySnapshot(
                samples=0,
                p50_ms=None,
                p95_ms=None,
                max_ms=None,
                negative_samples=0,
                clock_skew_suspected=False,
            )
        return LatencySnapshot(
            samples=len(samples),
            p50_ms=_percentile(samples, 0.50),
            p95_ms=_percentile(samples, 0.95),
            max_ms=samples[-1],
            negative_samples=0,
            clock_skew_suspected=False,
        )


def _percentile(sorted_samples: list[float], fraction: float) -> float:
    """Nearest-rank percentile. Exact and obvious for small windows; no
    interpolation, so a reported value is always one genuinely observed."""
    if not sorted_samples:
        raise ValueError("percentile of an empty sample")
    index = max(0, min(len(sorted_samples) - 1, round(fraction * len(sorted_samples)) - 1))
    return sorted_samples[index]
