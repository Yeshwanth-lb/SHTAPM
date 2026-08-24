"""ChannelFlagPolicy: Bridge from window-level anomaly to per-channel flags.

PROVISIONAL HEURISTIC — NOT VALIDATED FOR P2 ACCEPTANCE.

This module implements per-channel anomaly flagging using a variance-based
heuristic on the preprocessed Window features. The approach:

  1. If the window-level anomaly flag is False, flag NO channels.
  2. If the window-level anomaly flag is True:
     - Compute variance of each channel within the anomalous window
     - Flag channels where variance exceeds a threshold
     - Threshold is: (max_variance_in_window - min_variance_in_window) * factor

This method:
  ✓ Uses only the available Window features (no IF internals)
  ✓ Provides per-channel localization (vs. all-or-nothing)
  ✓ Is interpretable and deterministic
  ✗ Is NOT physics-based or validated on real data
  ✗ Requires threshold tuning on real datasets (U07-gated)

Threshold Parameter (U07-gated):
  The `variance_factor` parameter controls which channels are flagged when an
  anomaly occurs. Current default (0.5) flags channels in the upper 50% of
  variance distribution — this is arbitrary and must be tuned or validated
  on real SWaT/WADI/bench data before P2 acceptance. Do not rely on this
  default for production decisions.

Limitations (to be addressed in U07):
  - Variance-based selection does NOT prove causality
  - High variance ≠ anomaly cause (could be normal variation in a different phase)
  - Single heuristic cannot distinguish fault from attack; depends on AttributionEngine
  - No channel interactions or correlation knowledge
  - Limited to current IF output (window-level flag only)

When real per-channel IF contributions become available, this can be replaced
with a more principled localization method without changing the pipeline interface.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping

from app.schemas.contracts import CHANNELS

from edge.anomaly.detector import AnomalyResult
from edge.anomaly.preprocess import Window


class SeverityThresholdFlagPolicy:
    """Per-channel flags based on variance distribution within anomalous window.

    PROVISIONAL: threshold-based heuristic, not validated on real data.
    """

    def __init__(self, variance_factor: float = 0.5) -> None:
        """Initialize with variance-based flagging threshold.

        Args:
            variance_factor: Threshold multiplier for channel variance.
                Channels with variance > (min + factor * (max - min)) are flagged.
                Range: [0, 1]. Default 0.5 flags upper 50% of variance distribution.
                THIS IS U07-GATED: must be tuned on real data.
        """
        if not (0.0 <= variance_factor <= 1.0):
            raise ValueError(f"variance_factor must be in [0, 1], got {variance_factor}")
        self.variance_factor = variance_factor

    def flags(self, window: Window, anomaly: AnomalyResult) -> Mapping[str, bool]:
        """Map window-level anomaly to per-channel flags.

        Args:
            window: Preprocessed 30×6 window with features dict[channel] = tuple[values].
            anomaly: Window-level flag + severity from detector.

        Returns:
            dict[channel] -> bool. True means "flagged as anomalous".
            If anomaly.flag is False, all channels are False.
            If anomaly.flag is True, channels are flagged based on variance.
        """
        # If window is not anomalous at window level, flag nothing.
        if not anomaly.flag:
            return {ch: False for ch in CHANNELS}

        # Window is anomalous; apply per-channel heuristic.
        # Rows = samples, cols = channels in CHANNELS order
        matrix = window.as_matrix()

        # Compute variance per channel.
        variances: dict[str, float] = {}
        for ch_idx, ch in enumerate(CHANNELS):
            ch_values = [matrix[t][ch_idx] for t in range(len(matrix))]
            # Handle flat channels (zero variance).
            if len(ch_values) > 1:
                variances[ch] = statistics.variance(ch_values)
            else:
                variances[ch] = 0.0

        # Determine threshold: percentile based on variance distribution.
        if variances:
            min_var = min(variances.values())
            max_var = max(variances.values())
            var_range = max_var - min_var

            if var_range > 0.0:
                threshold = min_var + self.variance_factor * var_range
            else:
                # All channels have same variance (all flat, or all same); flag none.
                threshold = min_var + 1.0  # Ensure no channel passes

        else:
            # Should not happen (CHANNELS is not empty), but be safe.
            threshold = float("inf")

        # Flag channels above threshold.
        return {ch: variances[ch] > threshold for ch in CHANNELS}
