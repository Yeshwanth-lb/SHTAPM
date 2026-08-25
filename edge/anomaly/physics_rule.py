"""Minimal, provisional PhysicsRule (P2 · unblocks AttributionEngine only).

Before this module, NO concrete PhysicsRule implementation existed anywhere
in the codebase (D011 D) — AttributionEngine's constructor requires one, but
every caller (production wiring, edge/eval/swat_eval.py) had to pass a stub
that never reports a violation, meaning attribution=attack was structurally
unreachable everywhere. This module exists ONLY to unblock that wiring path
so P2-ANOM-E2/O3-style attribution can be exercised end-to-end at all — it is
NOT a validated physics claim, and its scope is deliberately narrow.

Reuses, rather than invents, physics: the ONLY approved cross-sensor
relationship anywhere in this codebase is D010's current<->vibration
trend-sign heuristic (see edge/trust/k_correlation.py — that heuristic is
mechanically identical here, just reused to name an attribution suspect
instead of feeding the `k` trust signal). No new physics, tolerance, or
channel pair is introduced.

Deliberately narrow scope — do NOT broaden without a new decision:
  - Only ever names 'current' or 'vibration' as suspect_channel. No rule is
    defined for temperature/pressure/humidity/gas, exactly as D010 states
    for `k` ("k=1.0 does NOT claim these channels are healthy"). A
    constant-spoof or any other anomaly on those four channels can NEVER be
    attributed as 'attack' by this rule — it will fall through to 'fault'
    (if flagged) via AttributionEngine's existing branch logic, which is the
    documented, correct behaviour for an unflagged suspect, not a defect.
  - Inherits a KNOWN, PRE-EXISTING limitation of the underlying heuristic
    (already documented in k_correlation.py before this rule existed): a
    FLAT ("zero trend") channel is treated as agreeing with anything
    (product-of-signs rule: 0 * anything >= 0 passes). A pure constant-value
    spoof on current or vibration therefore produces NO violation and CANNOT
    be attributed as 'attack' by this rule, on any channel. This is not a
    new gap introduced here; broadening the rule to catch flat-vs-moving
    disagreement would be a new, undocumented physics tolerance, which is
    exactly what D010 already declined to do without real data.
  - When current and vibration genuinely disagree (opposing trend signs),
    the underlying heuristic treats BOTH as equally suspect (D010: "both
    channels receive k=0.0... we cannot determine which is lying without
    attribution"). Since PhysicsCheck can only name ONE suspect_channel,
    this rule breaks the tie by naming whichever of the two deviates
    further (by absolute z-score) from ITS OWN fitted clean-baseline mean —
    reusing the same fit-on-clean-baseline-only statistic already computed
    for ConsistencyProvider/IsolationForestDetector/ChannelFlagPolicy, not
    a new invented signal.

Must be fit() on clean-baseline windows only (same discipline as IF/`c`/
ChannelFlagPolicy) before use.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from edge.anomaly.attribution import PhysicsCheck
from edge.anomaly.preprocess import Window

_PAIR = ("current", "vibration")

REASON = (
    "physics violation: current/vibration trend-sign disagreement (D010 heuristic, provisional)"
)


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _trend_sign(samples: Sequence[float]) -> int:
    """Early-half-mean vs. late-half-mean sign, identical to
    CorrelationProvider._compute_pair_k's trend computation."""
    n = len(samples)
    mid = n // 2
    early = statistics.mean(samples[:mid])
    late = statistics.mean(samples[mid:])
    return _sign(late - early)


class TrendSignPhysicsRule:
    """Minimal provisional PhysicsRule. See module docstring for scope."""

    def __init__(self) -> None:
        self._train_mean: dict[str, float] = {}
        self._train_std: dict[str, float] = {}
        self._fitted = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, windows: Sequence[Window]) -> None:
        """Fit current/vibration baseline mean+std from clean-baseline
        windows only (D011-style discipline: no attack-labeled leakage)."""
        windows = list(windows)
        if not windows:
            raise ValueError("fit() requires at least one clean-baseline window")

        for ch in _PAIR:
            values: list[float] = []
            for w in windows:
                values.extend(w.features[ch])
            self._train_mean[ch] = statistics.fmean(values)
            self._train_std[ch] = statistics.pstdev(values) or 1e-8  # numerical stability only
        self._fitted = True

    def _own_baseline_z(self, window: Window, channel: str) -> float:
        mean_val = statistics.mean(window.features[channel])
        return abs((mean_val - self._train_mean[channel]) / self._train_std[channel])

    def check(self, window: Window) -> PhysicsCheck:
        if not self._fitted:
            raise RuntimeError("TrendSignPhysicsRule.check() called before fit(); call fit() first")

        current_trend = _trend_sign(window.features["current"])
        vibration_trend = _trend_sign(window.features["vibration"])

        if current_trend * vibration_trend >= 0:
            return PhysicsCheck(violated=False, suspect_channel=None, reason="")

        current_z = self._own_baseline_z(window, "current")
        vibration_z = self._own_baseline_z(window, "vibration")
        suspect = "current" if current_z >= vibration_z else "vibration"
        return PhysicsCheck(violated=True, suspect_channel=suspect, reason=REASON)
