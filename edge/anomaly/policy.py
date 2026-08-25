"""ChannelFlagPolicy: Bridge from window-level anomaly to per-channel flags.

PROVISIONAL HEURISTIC — NOT VALIDATED FOR P2 ACCEPTANCE.

Design history (Candidate B, replaces the original same-window cross-channel
variance rule):

    The original design flagged whichever channel(s) had the HIGHEST variance
    relative to the OTHER channels in the same window. Root-cause analysis
    (see project-state/CHANNELFLAGPOLICY_DESIGN_ANALYSIS.md and the P2
    acceptance-suite failures it explains) found this fails in the opposite
    direction for exactly the injection shapes it most needs to catch:

      - A single-sample spike: the outlier dominates that channel's own
        per-window min-max range, compressing its other 29 samples toward
        one end. The channel's OWN measured variance drops BELOW ordinary
        clean channels' noise-driven variance — the more extreme the spike,
        the lower it drops. (Empirically confirmed: P2-ANOM-H2 flagged every
        untouched channel except the actually-spiked one.)
      - A constant-value spoof, fully inside the injection: min-max
        normalization's flat-window branch maps it to all-zeros —
        EXACTLY zero variance, deterministically the lowest of all six
        channels. (P2-ANOM-H3 / P2-TRUST-H2's `h` floor.)

    Reversing the comparison (flag the lowest-variance channel instead of
    the highest) would catch both of those, but breaks on drift/ramp-shaped
    anomalies, whose post-normalization variance resembles ordinary noise —
    a reversed rule would then prefer some unrelated, naturally-quieter
    channel over the genuinely drifting one. A single scalar, compared
    across channels within one window, cannot represent all these shapes at
    once: the failure is structural, not a threshold/direction tuning
    problem.

    Candidate B: keep the same per-channel variance statistic (still
    computed on the already-normalized ``Window`` — no change to
    ``Preprocessor``/``Window``), but stop comparing channels to each other
    within one window. Instead, ``fit()`` learns each channel's OWN baseline
    distribution of window-variance from clean-baseline windows (same
    fit-only-on-clean discipline as ``IsolationForestDetector``/
    ``ConsistencyProvider``), and ``flags()`` does a two-sided empirical-CDF
    comparison: is this channel's CURRENT variance abnormally low (spike,
    constant-spoof) OR abnormally high (relative to that specific channel's
    own normal spread), instead of abnormally high relative to its
    neighbours in this one window.

    This does NOT fix everything: drift/ramp-shaped anomalies may still
    produce a variance within that channel's own normal range (ambiguous by
    construction), and a replay attack is statistically indistinguishable
    from genuine history by shape alone. Both remain open, unresolved by
    this change — see project-state/CHANNELFLAGPOLICY_DESIGN_ANALYSIS.md.

This method:
  ✓ Uses only the available Window features (no IF internals)
  ✓ Provides per-channel localization (vs. all-or-nothing)
  ✓ Is interpretable and deterministic
  ✓ Compares each channel only to its own history (no cross-channel
    apples-to-oranges comparison)
  ✗ Is NOT physics-based or validated on real data
  ✗ Requires threshold tuning on real datasets (U07-gated)
  ✗ Does not distinguish drift/ramp from ordinary noise
  ✗ Cannot detect replay (statistically identical to genuine history)

Threshold parameter (U07-gated):
  ``tail_fraction`` (default 0.1) is the two-sided empirical-CDF tail: a
  channel is flagged if its current window-variance falls in the bottom
  ``tail_fraction`` or top ``tail_fraction`` of ITS OWN baseline variance
  distribution. This is an arbitrary, provisional default — not derived
  from real data — and must be tuned or validated on real SWaT/WADI/bench
  data before P2 acceptance, exactly as the original ``variance_factor``
  was.
"""

from __future__ import annotations

import bisect
import statistics
from collections.abc import Mapping, Sequence

from app.schemas.contracts import CHANNELS

from edge.anomaly.detector import AnomalyResult
from edge.anomaly.preprocess import Window


def _window_channel_variance(window: Window, channel: str) -> float:
    """Sample variance of one channel's values within a window (0.0 for a
    single-sample window, matching the previous implementation's handling)."""
    values = window.features[channel]
    if len(values) > 1:
        return statistics.variance(values)
    return 0.0


class SeverityThresholdFlagPolicy:
    """Per-channel flags based on each channel's OWN baseline variance
    distribution (two-sided empirical CDF).

    PROVISIONAL: still a heuristic, not validated on real data. See module
    docstring for the Candidate B design rationale.
    """

    def __init__(self, tail_fraction: float = 0.1) -> None:
        """Initialize with a two-sided empirical-CDF tail fraction.

        Args:
            tail_fraction: a channel is flagged if its current window
                variance falls in the bottom ``tail_fraction`` or top
                ``tail_fraction`` of that SAME channel's fitted baseline
                variance distribution. Range: [0, 1]. THIS IS U07-GATED:
                an arbitrary, provisional default, must be tuned on real
                data.
        """
        if not (0.0 <= tail_fraction <= 1.0):
            raise ValueError(f"tail_fraction must be in [0, 1], got {tail_fraction}")
        self.tail_fraction = tail_fraction
        self._train_variance_sorted: dict[str, list[float]] = {}
        self._fitted = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    def fit(self, windows: Sequence[Window]) -> None:
        """Learn each channel's own baseline distribution of window-variance
        from clean-baseline windows. Must be fit on Normal-only windows —
        the same discipline already required of ``IsolationForestDetector``
        and ``ConsistencyProvider`` (no Attack-labeled leakage).

        Raises:
            ValueError: if windows is empty.
        """
        windows = list(windows)
        if not windows:
            raise ValueError("fit() requires at least one clean-baseline window")

        variances_by_channel: dict[str, list[float]] = {ch: [] for ch in CHANNELS}
        for window in windows:
            for ch in CHANNELS:
                variances_by_channel[ch].append(_window_channel_variance(window, ch))

        self._train_variance_sorted = {ch: sorted(vs) for ch, vs in variances_by_channel.items()}
        self._fitted = True

    def flags(self, window: Window, anomaly: AnomalyResult) -> Mapping[str, bool]:
        """Map window-level anomaly to per-channel flags.

        Args:
            window: Preprocessed 30×6 window with features dict[channel] = tuple[values].
            anomaly: Window-level flag + severity from detector.

        Returns:
            dict[channel] -> bool. True means "flagged as anomalous" (this
            channel's current variance is an outlier — high or low —
            relative to ITS OWN fitted baseline distribution).
            If anomaly.flag is False, all channels are False.

        Raises:
            RuntimeError: if fit() has not been called.
        """
        if not anomaly.flag:
            return {ch: False for ch in CHANNELS}

        if not self._fitted:
            raise RuntimeError(
                "SeverityThresholdFlagPolicy.flags() called before fit(); call fit() first"
            )

        out: dict[str, bool] = {}
        for ch in CHANNELS:
            current_var = _window_channel_variance(window, ch)
            train_sorted = self._train_variance_sorted[ch]
            n = len(train_sorted)
            # Empirical CDF: fraction of baseline windows with variance <= current_var.
            rank = bisect.bisect_right(train_sorted, current_var)
            percentile = rank / n
            out[ch] = percentile <= self.tail_fraction or percentile >= (1.0 - self.tail_fraction)
        return out
