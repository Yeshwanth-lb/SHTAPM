"""Operating-state consistency physics rule for fault-vs-attack attribution.

WHY THIS RULE EXISTS. ``TrendSignPhysicsRule`` (D013) compares the up/down
trend of current and vibration within a window. Measured on 2026-10-26 it
attributed 40% of injected episodes correctly and labelled real physical
events (a tap, a motor switch-on) as attacks (D030). Two structural reasons:

  * Trend direction is noise at idle (the channels are physically unrelated
    there, D033) and coincides for many genuine faults.
  * Several fault and attack types in PRD §12.4 are the SAME waveform on a
    single channel: drift == ramp injection, a long spike == bias injection,
    stuck-at == constant spoof at the current value. No single-channel shape
    statistic can separate them. Only physics can: does the reading agree with
    what the other sensors say is physically happening?

THE PHYSICS. A pump motor is either running or idle, and BOTH current and
vibration reflect that state (bench evidence: idle window medians current
<= 0.0002 A, vibration <= 0.35 g; running current >= 0.31 A, vibration
median 0.68 g; D010, D033). Each channel therefore gives an INDEPENDENT
estimate of the motor state. Two estimates that disagree describe a
physically impossible machine:

  * current says running while vibration says idle (or the reverse) ->
    one reading is false -> ``violated=True`` -> attack on the suspect.

THE SUSPECT is the channel whose state estimate CHANGED most recently while
the other stayed put. A motor that really starts or stops moves both channels
together (D030's mislabelled switch-on becomes consistent); a single falsified
channel moves alone.

ROBUSTNESS BY CONSTRUCTION:
  * State comes from the window MEDIAN, so impulsive events (a tap, a
    one-sample glitch, a short spike) do not flip it: those stay faults.
  * Each channel has a hysteresis band (neither idle nor running). A window
    in the band gives no verdict, so motor transitions, partial windows and
    low-vibration running never produce a violation.
  * No verdict without raw frames: the normalised window cannot express
    absolute level, so the rule needs ``observe_raw_window`` before ``check``.

SCOPE AND HONEST LIMITS. The rule covers the physically coupled pair only
(current, vibration); the other channels have no physical partner on this
bench and can only be attributed ``fault``. It cannot catch an attack that
keeps the falsified channel in the SAME state as reality (a plausible replay,
a spoof at the true value, a slow ramp that never crosses a state boundary):
such readings are physically consistent by definition and need other
evidence (timing/watermarking) — reported as limitations, not hidden.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas.contracts import TelemetryMessage

from edge.anomaly.attribution import PhysicsCheck
from edge.anomaly.preprocess import Window

IDLE = "idle"
RUNNING = "running"
UNCLEAR = "unclear"

REASON = (
    "physics violation: {suspect} says the motor is {suspect_state} while "
    "{other} says it is {other_state}"
)


@dataclass(frozen=True)
class StateBands:
    """Per-channel motor-state bands on the raw window median.

    ``idle_max`` and ``running_min`` must leave a gap: medians inside it give
    no verdict."""

    idle_max: float
    running_min: float

    def __post_init__(self) -> None:
        if not self.idle_max < self.running_min:
            raise ValueError("idle_max must be below running_min (a hysteresis gap is required)")

    def classify(self, median: float) -> str:
        if median <= self.idle_max:
            return IDLE
        if median >= self.running_min:
            return RUNNING
        return UNCLEAR


# Bench calibration (2026-10-26, 30-sample window medians, idle captures of
# 7.2 h + 40 min and the 19-min motor-load capture). Re-measure if the motor,
# its supply or the ADXL335 mounting changes.
BENCH_CURRENT_BANDS = StateBands(idle_max=0.05, running_min=0.3)
BENCH_VIBRATION_BANDS = StateBands(idle_max=0.35, running_min=0.5)


class OperatingStateRule:
    """``PhysicsRule`` judging current<->vibration motor-state consistency."""

    def __init__(
        self,
        current_bands: StateBands = BENCH_CURRENT_BANDS,
        vibration_bands: StateBands = BENCH_VIBRATION_BANDS,
    ) -> None:
        self._bands = {"current": current_bands, "vibration": vibration_bands}
        self._raw: Sequence[TelemetryMessage] | None = None
        # Last determinate state per channel and the window count at which it
        # was entered, to tell which channel moved most recently.
        self._state: dict[str, str] = {}
        self._since: dict[str, int] = {}
        self._tick = 0
        self._fitted = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, windows: Sequence[Window]) -> None:
        """Present for the shared fit contract (``LiveP2Monitor`` fits every
        rule on clean windows). This rule's bands are calibrated from raw
        bench data, not learned from normalised windows, so fitting only
        resets the state history."""
        if not windows:
            raise ValueError("fit() requires at least one clean-baseline window")
        self._state.clear()
        self._since.clear()
        self._tick = 0
        self._fitted = True

    def observe_raw_window(self, frames: Sequence[TelemetryMessage]) -> None:
        """Raw frames of the window about to be checked (see module docstring)."""
        self._raw = frames
        self._tick += 1
        for channel, bands in self._bands.items():
            state = bands.classify(statistics.median(getattr(f.sensors, channel) for f in frames))
            if state != UNCLEAR and self._state.get(channel) != state:
                self._state[channel] = state
                self._since[channel] = self._tick

    def check(self, window: Window) -> PhysicsCheck:
        if not self._fitted:
            raise RuntimeError("OperatingStateRule must be fit() before check()")
        raw, self._raw = self._raw, None
        if raw is None:
            return PhysicsCheck(violated=False, suspect_channel=None, reason="")
        states = {
            ch: bands.classify(statistics.median(getattr(f.sensors, ch) for f in raw))
            for ch, bands in self._bands.items()
        }
        if UNCLEAR in states.values() or states["current"] == states["vibration"]:
            return PhysicsCheck(violated=False, suspect_channel=None, reason="")
        # Disagreement: the channel that changed state most recently is the
        # suspect. A tie (both entered their states in the same window) cannot
        # be resolved from physics alone and names no suspect.
        since_cur = self._since.get("current", 0)
        since_vib = self._since.get("vibration", 0)
        if since_cur == since_vib:
            return PhysicsCheck(violated=True, suspect_channel=None, reason="physics violation")
        suspect, other = (
            ("current", "vibration") if since_cur > since_vib else ("vibration", "current")
        )
        return PhysicsCheck(
            violated=True,
            suspect_channel=suspect,
            reason=REASON.format(
                suspect=suspect,
                suspect_state=states[suspect],
                other=other,
                other_state=states[other],
            ),
        )
