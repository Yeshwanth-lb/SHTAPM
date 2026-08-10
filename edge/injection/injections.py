"""Synthetic §12.4 fault/attack injections as pure stream transforms (P2).

Each injection is a small dataclass carrying its REQUIRED parameters (channel +
onset + duration, plus a per-type magnitude where applicable). ``apply(frames)``
returns a new stream plus per-frame ground-truth :class:`Label` metadata.

Purity: the input list and its frames are never mutated. Inactive frames are
passed through unchanged (frozen pydantic messages are safe to share); active
frames are rebuilt via the shared ``build_telemetry`` so the frozen wire
contract is preserved and only the targeted channel changes.

No magnitude/duration/threshold is baked in — §12.4 specifies none, so callers
must supply them. The fault-vs-attack grouping (``Kind``) is the documented
§12.4 taxonomy, not a physics claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, TelemetryMessage


class Kind(str, Enum):
    """Documented §12.4 top-level grouping."""

    FAULT = "fault"
    ATTACK = "attack"


class InjectionType(str, Enum):
    """The 7 hardware-free §12.4 injection types (dry-run excluded — physical)."""

    DRIFT = "drift"
    SPIKE = "spike"
    STUCK_AT = "stuck_at"
    BIAS_FDI = "bias_fdi"
    RAMP_FDI = "ramp_fdi"
    REPLAY = "replay"
    CONSTANT_SPOOF = "constant_spoof"


FAULT_TYPES: frozenset[InjectionType] = frozenset(
    {InjectionType.DRIFT, InjectionType.SPIKE, InjectionType.STUCK_AT}
)
ATTACK_TYPES: frozenset[InjectionType] = frozenset(
    {
        InjectionType.BIAS_FDI,
        InjectionType.RAMP_FDI,
        InjectionType.REPLAY,
        InjectionType.CONSTANT_SPOOF,
    }
)


@dataclass(frozen=True)
class Label:
    """Per-frame ground truth (tests/evaluation only — never on the wire)."""

    index: int
    sample_seq: int
    channel: str
    injection_type: InjectionType
    kind: Kind
    active: bool


@dataclass(frozen=True)
class InjectionResult:
    """Output of :meth:`Injection.apply`: transformed stream + aligned labels."""

    frames: list[TelemetryMessage]
    labels: list[Label]


def _channel_value(frame: TelemetryMessage, channel: str) -> float:
    return float(getattr(frame.sensors, channel))


def _rebuild_with(frame: TelemetryMessage, channel: str, value: float) -> TelemetryMessage:
    """Return a new frame identical to ``frame`` but with ``channel`` set to
    ``value``. Other channels, device_id, ts, and sample_seq are preserved."""
    values = {ch: _channel_value(frame, ch) for ch in CHANNELS}
    values[channel] = value
    return build_telemetry(frame.device_id, frame.ts, values, frame.sample_seq)


@dataclass(frozen=True)
class Injection:
    """Base injection: targets one ``channel`` over ``[onset, onset+duration)``
    (indices into the stream). Subclasses define the per-sample value."""

    # Type/kind are fixed per subclass.
    injection_type: ClassVar[InjectionType]
    kind: ClassVar[Kind]

    channel: str
    onset: int
    duration: int

    def __post_init__(self) -> None:
        if self.channel not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}, got {self.channel!r}")
        if self.onset < 0:
            raise ValueError(f"onset must be >= 0, got {self.onset}")
        if self.duration < 1:
            raise ValueError(f"duration must be >= 1, got {self.duration}")

    def _active(self, i: int) -> bool:
        return self.onset <= i < self.onset + self.duration

    def _value(self, i: int, frames: list[TelemetryMessage]) -> float:
        """Injected value for active index ``i``. ``i - self.onset`` is the
        0-based step within the injection window."""
        raise NotImplementedError

    def _validate_against(self, frames: list[TelemetryMessage]) -> None:
        """Optional extra validation once the target stream length is known."""

    def apply(self, frames: list[TelemetryMessage]) -> InjectionResult:
        self._validate_against(frames)
        out: list[TelemetryMessage] = []
        labels: list[Label] = []
        for i, frame in enumerate(frames):
            active = self._active(i)
            if active:
                new_frame = _rebuild_with(frame, self.channel, self._value(i, frames))
            else:
                new_frame = frame  # unchanged passthrough (input never mutated)
            out.append(new_frame)
            labels.append(
                Label(
                    index=i,
                    sample_seq=frame.sample_seq,
                    channel=self.channel,
                    injection_type=self.injection_type,
                    kind=self.kind,
                    active=active,
                )
            )
        return InjectionResult(frames=out, labels=labels)


# --- faults -----------------------------------------------------------------


@dataclass(frozen=True)
class Drift(Injection):
    """Gradual drift (fault): cumulative additive offset ``rate`` per sample
    over the window. ``rate`` is a required caller value (no spec default)."""

    injection_type: ClassVar[InjectionType] = InjectionType.DRIFT
    kind: ClassVar[Kind] = Kind.FAULT

    rate: float

    def _value(self, i: int, frames: list[TelemetryMessage]) -> float:
        step = i - self.onset + 1  # 1-based ramp within the window
        return _channel_value(frames[i], self.channel) + self.rate * step


@dataclass(frozen=True)
class Spike(Injection):
    """Sudden spike (fault): additive ``amplitude`` on each active sample
    (``duration`` controls how many). ``amplitude`` is required."""

    injection_type: ClassVar[InjectionType] = InjectionType.SPIKE
    kind: ClassVar[Kind] = Kind.FAULT

    amplitude: float

    def _value(self, i: int, frames: list[TelemetryMessage]) -> float:
        return _channel_value(frames[i], self.channel) + self.amplitude


@dataclass(frozen=True)
class StuckAt(Injection):
    """Stuck-at (fault): the channel freezes. By default it holds the value it
    had at ``onset``; an explicit ``held_value`` may override (both are caller
    choices, not spec magnitudes)."""

    injection_type: ClassVar[InjectionType] = InjectionType.STUCK_AT
    kind: ClassVar[Kind] = Kind.FAULT

    held_value: float | None = None

    def _value(self, i: int, frames: list[TelemetryMessage]) -> float:
        if self.held_value is not None:
            return self.held_value
        return _channel_value(frames[self.onset], self.channel)


# --- attacks ----------------------------------------------------------------


@dataclass(frozen=True)
class BiasFDI(Injection):
    """Bias false-data-injection (attack): constant additive ``bias`` on the
    window. ``bias`` is required."""

    injection_type: ClassVar[InjectionType] = InjectionType.BIAS_FDI
    kind: ClassVar[Kind] = Kind.ATTACK

    bias: float

    def _value(self, i: int, frames: list[TelemetryMessage]) -> float:
        return _channel_value(frames[i], self.channel) + self.bias


@dataclass(frozen=True)
class RampFDI(Injection):
    """Ramp false-data-injection (attack): cumulative additive ``slope`` per
    sample over the window. ``slope`` is required."""

    injection_type: ClassVar[InjectionType] = InjectionType.RAMP_FDI
    kind: ClassVar[Kind] = Kind.ATTACK

    slope: float

    def _value(self, i: int, frames: list[TelemetryMessage]) -> float:
        step = i - self.onset + 1
        return _channel_value(frames[i], self.channel) + self.slope * step


@dataclass(frozen=True)
class Replay(Injection):
    """Replay (attack): overwrite the window with the target channel's earlier
    values starting at ``source_onset`` (required). Sample-for-sample copy for
    the whole ``duration``."""

    injection_type: ClassVar[InjectionType] = InjectionType.REPLAY
    kind: ClassVar[Kind] = Kind.ATTACK

    source_onset: int

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.source_onset < 0:
            raise ValueError(f"source_onset must be >= 0, got {self.source_onset}")

    def _validate_against(self, frames: list[TelemetryMessage]) -> None:
        end = self.source_onset + self.duration
        if end > len(frames):
            raise ValueError(
                f"replay source segment [{self.source_onset}, {end}) exceeds "
                f"stream length {len(frames)}"
            )
        if self.source_onset + self.duration > self.onset:
            # Overlap would read frames that may themselves be under injection.
            raise ValueError("replay source segment must end at or before onset")

    def _value(self, i: int, frames: list[TelemetryMessage]) -> float:
        src = self.source_onset + (i - self.onset)
        return _channel_value(frames[src], self.channel)


@dataclass(frozen=True)
class ConstantSpoof(Injection):
    """Constant-value spoof (attack): pin the channel to a constant ``value``
    (required — a plausible value chosen by the caller, not a spec default)."""

    injection_type: ClassVar[InjectionType] = InjectionType.CONSTANT_SPOOF
    kind: ClassVar[Kind] = Kind.ATTACK

    value: float

    def _value(self, i: int, frames: list[TelemetryMessage]) -> float:
        return self.value
