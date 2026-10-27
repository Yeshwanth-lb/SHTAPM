"""Edge acquisition sampler (P1 · C2).

Reads all configured channels through C1 ``SensorDriver``s, assembles a frozen
``TelemetryMessage`` via the shared ``build_telemetry`` (no second builder), and
appends healthy frames to a bounded ring buffer. Configurable 1–10 Hz, monotonic
``sample_seq``, injectable clock. No hardware, no MQTT, no sleeping in
``sample_once`` (independently testable).

Unhealthy handling (decision C): the frozen ``TelemetryMessage`` has NO
per-channel health field, so an unhealthy channel CANNOT be represented on the
wire without a future contract change. Therefore, if ANY channel read is
unhealthy, ``sample_once`` does NOT build a frame — it returns a structured
``SampleResult`` carrying the C1 ``Reading``s (incl. ``value=None`` /
``healthy=False``) and ``frame=None``. No imputation, no dropping-to-zero, no
exception for an ordinary bad read. The eventual unhealthy wire representation
is an open, approval-gated contract decision.

DEGRADED MODE (D045, ``hold_last_good=True``, what the live edge uses): one
dead sensor no longer stops the whole stream (NFR-R1). A channel that WAS
healthy and stops responding keeps publishing its LAST GOOD reading, and the
result names it in ``stale`` -- the edge reports that set on the decision topic
so the dashboard shows "SENSOR DEAD" and the detector/trust layers see a
frozen channel. Never an invented value: a channel with no good reading since
start-up still withholds the frame, exactly as before.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.acquisition.ring_buffer import RingBuffer
from edge.drivers.base import Clock, Reading, SensorDriver, now_iso_ms

MIN_RATE_HZ = 1.0
MAX_RATE_HZ = 10.0
DEFAULT_BUFFER_CAPACITY = 120


@dataclass(frozen=True)
class SampleResult:
    """One sample tick. healthy → frame is a TelemetryMessage; unhealthy →
    frame is None and readings carry the per-channel health/values."""

    healthy: bool
    ts: str
    readings: dict[str, Reading]
    frame: TelemetryMessage | None
    # Channels whose value in ``frame`` is their last good reading (D045).
    stale: frozenset[str] = frozenset()


class Sampler:
    def __init__(
        self,
        *,
        device_id: str,
        drivers: Mapping[str, SensorDriver],
        clock: Clock = now_iso_ms,
        buffer_capacity: int = DEFAULT_BUFFER_CAPACITY,
        start_seq: int = 0,
        hold_last_good: bool = False,
    ) -> None:
        missing = set(CHANNELS) - set(drivers)
        extra = set(drivers) - set(CHANNELS)
        if missing or extra:
            raise ValueError(
                "drivers must cover exactly the frozen channels; "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        self._device_id = device_id
        self._drivers = dict(drivers)
        self._clock = clock
        self._seq = start_seq
        self._hold = hold_last_good
        self._last_good: dict[str, float] = {}
        self.buffer: RingBuffer[TelemetryMessage] = RingBuffer(buffer_capacity)

    def sample_once(self) -> SampleResult:
        """Read every channel once. No sleeping. Advances sample_seq only when a
        healthy frame is emitted (emitted seqs stay contiguous + monotonic)."""
        ts = self._clock()
        readings: dict[str, Reading] = {ch: self._drivers[ch].read() for ch in CHANNELS}
        for ch, reading in readings.items():
            if reading.healthy:
                self._last_good[ch] = reading.value
        unhealthy = frozenset(ch for ch, r in readings.items() if not r.healthy)
        if not unhealthy:
            return self._emit(ts, readings, {ch: readings[ch].value for ch in CHANNELS})
        if self._hold and all(ch in self._last_good for ch in unhealthy):
            values = {
                ch: (self._last_good[ch] if ch in unhealthy else readings[ch].value)
                for ch in CHANNELS
            }
            return self._emit(ts, readings, values, stale=unhealthy)
        return SampleResult(healthy=False, ts=ts, readings=readings, frame=None)

    def _emit(
        self,
        ts: str,
        readings: dict[str, Reading],
        values: dict[str, float],
        stale: frozenset[str] = frozenset(),
    ) -> SampleResult:
        frame = build_telemetry(self._device_id, ts, values, self._seq)
        self._seq += 1
        self.buffer.append(frame)
        return SampleResult(healthy=not stale, ts=ts, readings=readings, frame=frame, stale=stale)

    def run(
        self,
        rate_hz: float,
        *,
        should_continue: Callable[[], bool],
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """Sample at ``rate_hz`` (1–10) until ``should_continue()`` is False.
        ``sleep`` is injectable (default: real ``time.sleep``) so tests never
        block. Frames are buffered; a downstream publisher (C3) drains the buffer.
        """
        if not (MIN_RATE_HZ <= rate_hz <= MAX_RATE_HZ):
            raise ValueError(f"rate_hz must be in [{MIN_RATE_HZ}, {MAX_RATE_HZ}], got {rate_hz}")
        if sleep is None:
            import time

            sleep = time.sleep
        period = 1.0 / rate_hz
        while should_continue():
            self.sample_once()
            sleep(period)
