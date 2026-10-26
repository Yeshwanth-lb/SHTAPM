"""Live scenario injection: apply one ``edge.injection`` transform to the
running telemetry stream for a bounded time (FR-A4 / FR-D7, D032).

The offline injections in ``injections.py`` transform a finished list of
frames. Live, frames arrive one per tick, so this module keeps the slice of
stream each injection needs and asks the SAME, unmodified injection class for
the value of each new frame. No second implementation of drift, spike, replay
etc. exists anywhere: the demo exercises exactly the code the evaluation does.

WHERE IT SITS. ``AcquisitionRuntime`` calls ``transform`` on every healthy
frame before monitoring and publishing, so the injected value is what P2
scores, what the dashboard draws, and what the backend stores -- the full
observable effect of a spoofed or failing sensor. It never touches drivers,
the relay, the watchdog or any actuation path.

UNITS. Command parameters are per second (``rate``, ``slope``) or in seconds
(``duration_s``, ``lookback_s``); the injection classes work per sample. This
module converts with the live sample rate, so a command means the same thing
at 1 Hz and at 10 Hz.

THREADING. Commands arrive on the MQTT client's thread; ``transform`` runs on
the acquisition thread. One lock guards all state, and ``transform`` never
raises: a bad injection ends itself and the clean frame is published.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field

from app.schemas.command import CancelCommand, InjectCommand
from app.schemas.contracts import TelemetryMessage

from edge.injection.injections import (
    AdaptiveStealthFDI,
    BiasFDI,
    ConstantSpoof,
    Drift,
    Injection,
    RampFDI,
    Replay,
    Spike,
    StuckAt,
    _rebuild_with,
)

log = logging.getLogger("shtapm.edge.injection.live")


@dataclass
class _Active:
    command: InjectCommand
    injection: Injection
    stream: list[TelemetryMessage] = field(default_factory=list)

    @property
    def end_index(self) -> int:
        return self.injection.onset + self.injection.duration


@dataclass(frozen=True)
class InjectionStatus:
    command_id: str
    scenario: str
    channel: str
    kind: str
    frames_done: int
    frames_total: int


class LiveInjector:
    """Holds at most one active injection. A new inject command replaces the
    running one; a cancel ends it (when its ``command_id`` matches, or for any
    cancel naming ``*``)."""

    def __init__(self, *, device_id: str, rate_hz: float, history_seconds: int) -> None:
        if rate_hz <= 0:
            raise ValueError(f"rate_hz must be > 0, got {rate_hz}")
        if history_seconds < 1:
            raise ValueError(f"history_seconds must be >= 1, got {history_seconds}")
        self._device_id = device_id
        self._rate_hz = rate_hz
        self._history: deque[TelemetryMessage] = deque(
            maxlen=max(1, math.ceil(history_seconds * rate_hz))
        )
        self._active: _Active | None = None
        self._lock = threading.Lock()

    # ---- commands (MQTT thread) -----------------------------------------------

    def submit(self, command: InjectCommand) -> bool:
        """Start ``command``. Returns False (logged, nothing changes) when it
        is for another device or cannot be satisfied from the live history."""
        if command.device_id != self._device_id:
            log.warning(
                "ignoring injection %s for device %s (this edge is %s)",
                command.command_id,
                command.device_id,
                self._device_id,
            )
            return False
        with self._lock:
            try:
                active = self._build(command)
            except ValueError as e:
                log.warning("rejected injection %s: %s", command.command_id, e)
                return False
            replaced = self._active
            self._active = active
        if replaced is not None:
            log.warning(
                "SCENARIO INJECTION %s replaced by %s",
                replaced.command.command_id,
                command.command_id,
            )
        log.warning(
            "SCENARIO INJECTION STARTED id=%s %s (%s) on %s for %ds params=%s by %s",
            command.command_id,
            command.scenario,
            command.kind,
            command.channel.value,
            command.duration_s,
            command.params,
            command.issued_by,
        )
        return True

    def cancel(self, command: CancelCommand) -> bool:
        with self._lock:
            active = self._active
            if active is None:
                return False
            if command.command_id not in (active.command.command_id, "*"):
                return False
            self._active = None
        log.warning(
            "SCENARIO INJECTION CANCELLED id=%s by %s",
            active.command.command_id,
            command.issued_by,
        )
        return True

    def status(self) -> InjectionStatus | None:
        with self._lock:
            active = self._active
            if active is None:
                return None
            done = max(0, len(active.stream) - active.injection.onset)
            return InjectionStatus(
                command_id=active.command.command_id,
                scenario=active.command.scenario,
                channel=active.command.channel.value,
                kind=active.command.kind,
                frames_done=done,
                frames_total=active.injection.duration,
            )

    # ---- per frame (acquisition thread) ---------------------------------------

    def transform(self, frame: TelemetryMessage) -> TelemetryMessage:
        """Return ``frame`` with the active injection applied, or unchanged."""
        with self._lock:
            # History always stores the CLEAN frame: a replay must copy what
            # the sensor really said, never an earlier injected value.
            self._history.append(frame)
            active = self._active
            if active is None:
                return frame
            active.stream.append(frame)
            index = len(active.stream) - 1
            finished = False
            try:
                value = active.injection._value(index, active.stream)
                if not math.isfinite(value):
                    raise ValueError(f"non-finite injected value {value!r}")
                out = _rebuild_with(frame, active.command.channel.value, value)
            except Exception as e:
                log.error("injection %s failed, ending it: %s", active.command.command_id, e)
                self._active = None
                return frame
            if index + 1 >= active.end_index:
                self._active = None
                finished = True
        if finished:
            log.warning("SCENARIO INJECTION ENDED id=%s", active.command.command_id)
        return out

    # ---- construction -----------------------------------------------------------

    def _frames(self, seconds: float) -> int:
        return max(1, round(seconds * self._rate_hz))

    def _per_sample(self, per_second: float) -> float:
        return per_second / self._rate_hz

    def _build(self, command: InjectCommand) -> _Active:
        """Map a command onto an injection whose onset is the NEXT frame."""
        channel = command.channel.value
        duration = self._frames(command.duration_s)
        p = command.params
        prefix: list[TelemetryMessage] = []
        scenario = command.scenario
        if scenario == "replay":
            lookback = self._frames(p["lookback_s"])
            if len(self._history) < lookback:
                raise ValueError(
                    f"replay needs {lookback} frames of history, only "
                    f"{len(self._history)} recorded since start"
                )
            prefix = list(self._history)[-lookback:]
            injection: Injection = Replay(
                channel=channel, onset=lookback, duration=duration, source_onset=0
            )
        elif scenario == "drift":
            injection = Drift(
                channel=channel, onset=0, duration=duration, rate=self._per_sample(p["rate"])
            )
        elif scenario == "spike":
            injection = Spike(channel=channel, onset=0, duration=duration, amplitude=p["amplitude"])
        elif scenario == "stuck_at":
            injection = StuckAt(
                channel=channel, onset=0, duration=duration, held_value=p.get("held_value")
            )
        elif scenario == "bias_fdi":
            injection = BiasFDI(channel=channel, onset=0, duration=duration, bias=p["bias"])
        elif scenario == "ramp_fdi":
            injection = RampFDI(
                channel=channel, onset=0, duration=duration, slope=self._per_sample(p["slope"])
            )
        elif scenario == "constant_spoof":
            injection = ConstantSpoof(channel=channel, onset=0, duration=duration, value=p["value"])
        elif scenario == "adaptive_stealth_fdi":
            injection = AdaptiveStealthFDI(
                channel=channel,
                onset=0,
                duration=duration,
                rate=self._per_sample(p["rate"]),
                residual_cap=p["residual_cap"],
            )
        else:  # unreachable: the contract's Literal lists exactly these eight
            raise ValueError(f"unknown scenario {scenario!r}")
        return _Active(command=command, injection=injection, stream=prefix)
