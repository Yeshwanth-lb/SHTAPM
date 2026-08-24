"""Consistency signal provider for the trust engine (P2 · U01).

Implements the ``c`` component of ``g = 0.4*c + 0.3*k + 0.3*h`` (FR-T2).

Design decision (revised Option 2, verified 2026-08-24)::

    c_ch = per-channel consistency signal via z-score residuals + empirical CDF

    Input: preprocessed per-channel values from Window (30 samples per channel).
    Baseline: per-channel mean/std computed from clean-baseline training windows.
    Method:
      1. For each sample in window: z_i = (x_i - baseline_mean) / baseline_std
      2. Aggregate: rms_z = sqrt(mean(z_i^2)) — RMS of z-scores within window
      3. Normalize: severity = empirical_CDF(rms_z in sorted training rms_z values)
      4. Invert: c_ch = 1 - severity (high when consistent, low when anomalous)

    Training: extract per-channel mean/std from clean-baseline windows.
              compute and store sorted RMS z-score distribution per-channel.

Coupling to FR-A1:
    ``c`` reuses the same training windows as the Isolation Forest detector.
    Both independently extract baseline statistics from those windows.
    No modification to iforest.py needed; complete isolation.

Orthogonality from ``h`` (historical reliability):
    ``c`` is per-window residual magnitude (instantaneous, no temporal memory).
    ``h`` integrates binary outcomes over 13-window horizon (temporal accumulation).
    Different observation type, timescale, and object; no shared computation.

No arbitrary constants:
    Empirical CDF calibration uses actual training distribution of rms_z values.
    Threshold ``1e-8`` added to std is numerical stability (prevent division by zero),
    not a tunable parameter.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Window


class ConsistencyProvider:
    """Per-channel consistency signal via z-score residuals from training baseline.

    Implements the SignalProvider protocol so it can be injected directly into
    ``TrustEngine.update_from_providers``.

    Typical per-window call sequence (managed by the caller, e.g. pipeline)::

        # 1. Train on clean baseline once at startup
        c_provider.fit(clean_baseline_windows)

        # 2. For each new window during operation:
        c_provider.record_window(current_window)

        # 3. Engine pulls c via evaluate()
        engine.update_from_providers(c_provider, k_provider, h_provider)

    The ``record_window`` call computes and caches c_ch for each channel;
    ``evaluate`` then retrieves the cached value. This ensures ``evaluate``
    only needs a channel name (satisfying the SignalProvider protocol).
    """

    def __init__(self) -> None:
        """Initialize with no training data; fit() must be called before use."""
        # Per-channel baseline statistics (set during fit)
        self._train_mean: dict[str, float] = {}
        self._train_std: dict[str, float] = {}
        self._train_rms_z_sorted: dict[str, np.ndarray] = {}

        # Current c values (set by record_window, read by evaluate)
        self._c: dict[str, float] = {ch: 0.5 for ch in CHANNELS}

        self._fitted = False

    # ------------------------------------------------------------------
    # Training (one-time initialization)
    # ------------------------------------------------------------------

    def fit(self, windows: Sequence[Window]) -> None:
        """Train on clean-baseline windows.

        Computes per-channel mean/std and stores the sorted distribution
        of RMS z-scores for each channel (used for empirical CDF).

        Must be called once at startup with the same clean-baseline windows
        that the anomaly detector (IF) trains on. This coupling ensures
        both use the same baseline without direct dependency.

        Args:
            windows: sequence of preprocessed clean-baseline windows.

        Raises:
            ValueError: if windows is empty.
        """
        windows = list(windows)
        if not windows:
            raise ValueError("fit() requires at least one clean-baseline window")

        # ----
        # Step 1: Extract per-channel data from all training windows
        # ----
        data_by_channel: dict[str, list[float]] = {ch: [] for ch in CHANNELS}
        for window in windows:
            for ch in CHANNELS:
                data_by_channel[ch].extend(window.features[ch])

        # ----
        # Step 2: Compute per-channel baseline (mean, std)
        # ----
        for ch in CHANNELS:
            data = np.array(data_by_channel[ch], dtype=float)
            self._train_mean[ch] = float(np.mean(data))
            self._train_std[ch] = float(np.std(data))

        # ----
        # Step 3: For each channel, compute RMS z-scores in each training window
        #         and store sorted distribution (for empirical CDF)
        # ----
        for ch in CHANNELS:
            rms_z_list = []
            for window in windows:
                # Extract this channel's samples from the window
                samples = np.array(window.features[ch], dtype=float)

                # Compute z-scores (how many stds away from baseline mean)
                z = (samples - self._train_mean[ch]) / (self._train_std[ch] + 1e-8)

                # Aggregate: RMS of z-scores (Euclidean norm in z-score space)
                rms_z = np.sqrt(np.mean(z**2))
                rms_z_list.append(rms_z)

            # Sort for empirical CDF lookup (via searchsorted)
            self._train_rms_z_sorted[ch] = np.sort(np.array(rms_z_list, dtype=float))

        self._fitted = True

    # ------------------------------------------------------------------
    # Per-window state update (called before evaluate)
    # ------------------------------------------------------------------

    def record_window(self, window: Window) -> None:
        """Compute and cache c values for the current window.

        Must be called once per window BEFORE ``evaluate()`` is called
        by TrustEngine. This ensures ``evaluate()`` only needs a channel
        name (satisfying the SignalProvider protocol).

        Args:
            window: the current preprocessed window.

        Raises:
            RuntimeError: if fit() has not been called.
            ValueError: for malformed window.
        """
        if not self._fitted:
            raise RuntimeError("record_window() called before fit(); call fit() first")

        for ch in CHANNELS:
            # Extract this channel's samples from the window
            samples = np.array(window.features[ch], dtype=float)

            # Compute z-scores relative to training baseline
            z = (samples - self._train_mean[ch]) / (self._train_std[ch] + 1e-8)

            # Aggregate into a single RMS score for the window
            rms_z = np.sqrt(np.mean(z**2))

            # Empirical CDF: rank this window's rms_z in the training distribution
            rank = int(np.searchsorted(self._train_rms_z_sorted[ch], rms_z, side="right"))
            severity = rank / len(self._train_rms_z_sorted[ch])

            # Invert to get consistency: high when severity is low (consistent)
            self._c[ch] = 1.0 - severity

    # ------------------------------------------------------------------
    # SignalProvider protocol
    # ------------------------------------------------------------------

    def evaluate(self, channel: str) -> float:
        """Return the current c value for ``channel`` in [0, 1].

        High (close to 1.0) when the channel behaves consistently with
        training baseline (present window has low residual magnitude).
        Low (close to 0.0) when the channel deviates (anomalous z-scores).

        Must be called AFTER ``record_window()`` has been called for the
        current window. The value returned is the one cached by record_window.

        Args:
            channel: channel name (must be one of CHANNELS).

        Returns:
            c value in [0, 1].

        Raises:
            ValueError: if channel is unknown.
        """
        if channel not in CHANNELS:
            raise ValueError(
                f"unknown channel {channel!r}; must be one of {CHANNELS}"
            )
        return self._c[channel]

    # ------------------------------------------------------------------
    # Introspection (test / debug)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, float]:
        """Return a copy of the current c values keyed by channel name."""
        return dict(self._c)

    @property
    def fitted(self) -> bool:
        """True if fit() has been called successfully."""
        return self._fitted
