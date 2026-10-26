"""Cross-sensor ``k`` from motor-state consistency (D035).

Replaces the trend-sign ``k`` (D010, gated by D033) in the live trust engine,
so trust and attribution reason with ONE physical model (``OperatingStateRule``,
D034) instead of two that can disagree.

WHY. The trend-sign rule compares the up/down trend of current and vibration
inside each window and gives both channels k = 0.0 when they disagree. During
steady operation -- idle (D033) and, measured on 2026-10-26, steady running --
both trends are noise, so the rule disagrees about half the time and drags
both channels toward Malicious on clean data. On the 2026-10-26 running
capture, neutralising k cut false isolation episodes from 7 to 2.

WHAT ``k`` MEANS HERE. k is 1.0 (no cross-sensor objection) unless current and
vibration describe a physically impossible motor state; then the suspect named
by the rule gets k = 0.0, or both channels when the rule cannot tell which one
moved. Channels without a physical partner always get 1.0, as before.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.operating_state_rule import OperatingStateRule
from edge.anomaly.preprocess import Window

_COUPLED = ("current", "vibration")
# The rule's bands are calibrated from raw bench data, not learned; its fit()
# only resets history and requires a window to satisfy the shared contract.
_RESET_WINDOW = Window(start_index=0, end_index=1, features={ch: (0.0,) for ch in CHANNELS})


class OperatingStateCorrelationProvider:
    """``SignalProvider`` for k backed by its own ``OperatingStateRule``."""

    def __init__(self, rule: OperatingStateRule | None = None) -> None:
        self._rule = rule if rule is not None else OperatingStateRule()
        self._rule.fit([_RESET_WINDOW])
        self._k: dict[str, float] = {ch: 1.0 for ch in CHANNELS}

    def observe_raw_window(self, frames: Sequence[TelemetryMessage]) -> None:
        """Raw frames for the window about to be recorded (the pipeline calls
        this before ``record_window``; normalised windows hide absolute level)."""
        self._rule.observe_raw_window(frames)

    def record_window(self, window: Window) -> None:
        check = self._rule.check(window)
        k = {ch: 1.0 for ch in CHANNELS}
        if check.violated:
            suspects = (check.suspect_channel,) if check.suspect_channel else _COUPLED
            for ch in suspects:
                k[ch] = 0.0
        self._k = k

    def evaluate(self, channel: str) -> float:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}; must be one of {CHANNELS}")
        return self._k[channel]

    def snapshot(self) -> dict[str, float]:
        return dict(self._k)
