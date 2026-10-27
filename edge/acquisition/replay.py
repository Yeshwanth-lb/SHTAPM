"""Recorded-session fallback profile (PRD §18.4 step 8, Doc06 P7-8, D040).

``ReplaySampler`` is a drop-in for ``Sampler``: ``AcquisitionRuntime`` calls
only ``sample_once()``, so a replayed frame goes through exactly the live path
-- scenario injection, P2 detection, trust, attribution, isolation, self-heal,
decision publishing, the backend and the dashboard. "Identical narrative, same
dashboard": only the source of the six numbers changes.

SOURCE: a telemetry capture in the edge's own wire format (``mosquitto_sub -t
shtapm/<id>/telemetry`` output, as recorded for a P2 baseline), so any clean
bench session can be the fallback. Each tick serves the next recorded frame
with a FRESH timestamp and sample_seq -- the backend and dashboard see a live
stream, not 2026-10-27 timestamps -- and loops at the end of the file.

HONESTY: replayed values are recorded measurements, not live ones. The edge
logs the replay source at startup and the profile is selected only explicitly
(``EDGE_SOURCE=replay``); it is never a silent fallback.

LIMITS: at the loop point the stream jumps from the file's last frame to its
first; P2 may flag the windows spanning that seam. Record the session so it
starts and ends in the same motor state (idle) to keep the seam quiet.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.acquisition.ring_buffer import RingBuffer
from edge.acquisition.sampler import DEFAULT_BUFFER_CAPACITY, SampleResult
from edge.drivers.base import Clock, Reading, now_iso_ms
from edge.models.p2_baseline import parse_capture


class ReplaySourceError(ValueError):
    """The replay file is missing, unreadable, or holds no telemetry frame."""


def load_replay_frames(path: str | Path) -> tuple[TelemetryMessage, ...]:
    """Every valid telemetry frame in ``path``, in recorded order.

    Raises ``ReplaySourceError`` naming the file when it cannot be used: a
    fallback that fails at the moment it is needed must fail loudly, at boot."""
    source = Path(path)
    if not source.is_file():
        raise ReplaySourceError(f"FALLBACK_REPLAY_PATH {source} does not exist")
    with source.open(encoding="utf-8") as handle:
        parsed = parse_capture(handle)
    if not parsed.messages:
        raise ReplaySourceError(
            f"FALLBACK_REPLAY_PATH {source} holds no valid telemetry frame "
            f"({parsed.rejected_line_count} malformed lines)"
        )
    return parsed.messages


class ReplaySampler:
    """Serves recorded frames one per tick, re-stamped, looping at the end."""

    def __init__(
        self,
        *,
        device_id: str,
        frames: Sequence[TelemetryMessage],
        clock: Clock = now_iso_ms,
        buffer_capacity: int = DEFAULT_BUFFER_CAPACITY,
        start_seq: int = 0,
    ) -> None:
        if not frames:
            raise ReplaySourceError("replay needs at least one frame")
        self._device_id = device_id
        self._frames = tuple(frames)
        self._clock = clock
        self._seq = start_seq
        self._cursor = 0
        self.loops = 0
        self.buffer: RingBuffer[TelemetryMessage] = RingBuffer(buffer_capacity)

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def sample_once(self) -> SampleResult:
        """Next recorded frame as a healthy, freshly stamped telemetry frame."""
        recorded = self._frames[self._cursor]
        self._cursor += 1
        if self._cursor == len(self._frames):
            self._cursor = 0
            self.loops += 1
        ts = self._clock()
        values = {ch: float(getattr(recorded.sensors, ch)) for ch in CHANNELS}
        frame = build_telemetry(self._device_id, ts, values, self._seq)
        self._seq += 1
        self.buffer.append(frame)
        readings = {ch: Reading(value=values[ch], unit="", ts=ts, healthy=True) for ch in CHANNELS}
        return SampleResult(healthy=True, ts=ts, readings=readings, frame=frame)
