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


class Sampler:
    def __init__(
        self,
        *,
        device_id: str,
        drivers: Mapping[str, SensorDriver],
        clock: Clock = now_iso_ms,
        buffer_capacity: int = DEFAULT_BUFFER_CAPACITY,
        start_seq: int = 0,
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
        self.buffer: RingBuffer[TelemetryMessage] = RingBuffer(buffer_capacity)

    def sample_once(self) -> SampleResult:
        """Read every channel once. No sleeping. Advances sample_seq only when a
        healthy frame is emitted (emitted seqs stay contiguous + monotonic)."""
        ts = self._clock()
        readings: dict[str, Reading] = {ch: self._drivers[ch].read() for ch in CHANNELS}
        if all(r.healthy for r in readings.values()):
            values = {ch: readings[ch].value for ch in CHANNELS}
            frame = build_telemetry(self._device_id, ts, values, self._seq)
            self._seq += 1
            self.buffer.append(frame)
            return SampleResult(healthy=True, ts=ts, readings=readings, frame=frame)
        return SampleResult(healthy=False, ts=ts, readings=readings, frame=None)

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
