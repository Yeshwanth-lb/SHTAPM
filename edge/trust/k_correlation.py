"""Cross-sensor correlation signal provider for the trust engine (P2 · U02, PROVISIONAL).

Implements the ``k`` component of ``g = 0.4*c + 0.3*k + 0.3*h`` (FR-T2).

⚠️ PROVISIONAL HEURISTIC (NOT VALIDATED PHYSICS):
    The current↔vibration rule ("both channels must trend in the same direction")
    is a proof-of-concept heuristic. It is NOT validated against real pump data
    and has NOT been tested on labeled attacks. This implementation satisfies
    FR-A2 (inject cross-sensor checks) but is known to be incomplete.

    Real physics will replace this when:
    - SWaT/WADI dataset becomes available (U07)
    - Real current↔vibration correlation is measured
    - Tolerance/thresholds are tuned on attack data

Scope:
    This provider defines k ONLY for the current↔vibration pair.
    All other channels receive k=1.0 (no rule defined for them).
    This does NOT mean those channels cannot be anomalous; c and h detect that.

Design:
    - Early vs. late window halves compared (early: [0:mid], late: [mid:n])
    - Trend detected via mean; sign compared (product rule)
    - Split derived from window.size (not hardcoded); adaptive to window length
    - No tunable parameters

Orthogonality from ``c`` (consistency):
    ``c`` measures per-window residual magnitude (instantaneous, no training).
    ``k`` measures cross-channel trend consistency (also instantaneous, no training).
    Different observation type and object; no shared computation.

Orthogonality from ``h`` (historical reliability):
    ``h`` integrates binary outcomes over 13-window horizon (temporal memory).
    ``k`` is purely instantaneous (depends only on current window).
    Different timescale and observation type; no shared computation.

Coupling to attribution:
    When current↔vibration trends disagree, both channels receive k=0.0 (both
    suspect) because we cannot determine which is lying without attribution.
    The AttributionEngine will later apply domain-specific rules to determine
    whether the violation is due to a faulty current sensor, faulty vibration
    sensor, or a spoofed signal (attack).

Non-involved channels:
    Temperature, pressure, humidity, gas: k=1.0 (these channels are not
    constrained by the current↔vibration rule). A k=1.0 value does NOT claim
    these channels are healthy — anomalies are detected by c and h.

Known limitations (provisional heuristic, not validated physics):
    - One rising + one flat trend passes (product=0≥0). This is a known
      limitation of the trend-sign rule. Real validation needed before
      considering a fix (e.g., epsilon threshold).
    - Unit/behavioral tests validate logic only, NOT real P2 acceptance
      (P2-TRUST-H2, P2-ANOM-H3). Acceptance requires SWaT/WADI data.
"""

from __future__ import annotations

import statistics

from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Window


def _sign(x: float) -> int:
    """Return -1, 0, or +1 for negative, zero, or positive."""
    if x > 0:
        return 1
    elif x < 0:
        return -1
    else:
        return 0


class CorrelationProvider:
    """Per-channel cross-sensor correlation signal (PROVISIONAL HEURISTIC).

    Implements the SignalProvider protocol. Detects violations of the provisional
    rule: "current and vibration must trend in the same direction."

    ⚠️ This is a proof-of-concept. Real physics validation requires SWaT/WADI
    data. Do not claim this detects real attacks without labeled dataset validation.

    Typical per-window call sequence (managed by the caller, e.g. pipeline)::

        # 1. For each new window during operation:
        k_provider.record_window(current_window)

        # 2. Engine pulls k via evaluate(); used in trust update
        engine.update_from_providers(c_provider, k_provider, h_provider)

    State is per-window only (no training phase like c_provider.fit()).
    """

    def __init__(self) -> None:
        """Initialize with neutral k=0.5 for all channels (no evidence yet)."""
        self._k: dict[str, float] = {ch: 0.5 for ch in CHANNELS}

    # ------------------------------------------------------------------
    # Per-window state update
    # ------------------------------------------------------------------

    def record_window(self, window: Window) -> None:
        """Evaluate the provisional heuristic and cache k values.

        Applies the trend-sign rule to current and vibration. Other channels
        receive k=1.0 (not constrained by this rule).

        This is NOT anomaly detection for non-involved channels; c and h handle
        that. k only encodes the current↔vibration physics relationship.

        Args:
            window: the current preprocessed window.

        Raises:
            ValueError: for malformed window.
        """
        current_samples = window.features.get("current")
        vibration_samples = window.features.get("vibration")

        if current_samples is None or vibration_samples is None:
            raise ValueError("window must contain 'current' and 'vibration' features")

        if len(current_samples) != len(vibration_samples):
            raise ValueError(
                f"current and vibration must have same length; "
                f"got {len(current_samples)} and {len(vibration_samples)}"
            )

        # Compute the trend-sign heuristic
        pair_k = self._compute_pair_k(current_samples, vibration_samples)

        # Assign k values per channel
        self._k["current"] = pair_k
        self._k["vibration"] = pair_k

        # Other channels not constrained by this rule
        for ch in ["temperature", "pressure", "humidity", "gas"]:
            self._k[ch] = 1.0

    def _compute_pair_k(
        self, current_samples: tuple[float, ...], vibration_samples: tuple[float, ...]
    ) -> float:
        """Evaluate the provisional current↔vibration trend-sign heuristic.

        Rule: "Both channels must trend in the same direction (or both flat)."

        Early and late halves are derived from the actual window length, not
        hardcoded. For a 30-sample window: early=[0:15], late=[15:30].

        Known limitation (provisional heuristic, not validated physics):
            One rising + one flat: passes (product = 0 ≥ 0). This is a known
            limitation of the trend-sign rule that does not distinguish between
            "both zero" and "one non-zero, one zero". Real physics validation
            would require SWaT/WADI data to determine if this behavior is
            acceptable or needs refinement. Do not introduce an epsilon threshold
            to "fix" this without data-backed justification.

        Args:
            current_samples: tuple of preprocessed current values [0,1]
            vibration_samples: tuple of preprocessed vibration values [0,1]

        Returns:
            1.0 if trends are consistent (both rising, both falling, both flat)
            0.0 if trends oppose (one rising, one falling)
        """
        n = len(current_samples)
        mid = n // 2

        # Current trend: early vs. late half
        current_early = statistics.mean(current_samples[:mid])
        current_late = statistics.mean(current_samples[mid:])
        current_trend = _sign(current_late - current_early)

        # Vibration trend: early vs. late half
        vibration_early = statistics.mean(vibration_samples[:mid])
        vibration_late = statistics.mean(vibration_samples[mid:])
        vibration_trend = _sign(vibration_late - vibration_early)

        # Rule: trends must have same sign (or both zero)
        # Passes: (+1)*( +1)=+1≥0, (-1)*(-1)=+1≥0, 0*X=0≥0
        # Fails:  (+1)*(-1)=-1<0
        if current_trend * vibration_trend >= 0:
            return 1.0
        else:
            return 0.0

    # ------------------------------------------------------------------
    # SignalProvider protocol
    # ------------------------------------------------------------------

    def evaluate(self, channel: str) -> float:
        """Return the current k value for ``channel`` in [0, 1].

        High (1.0) when the channel's cross-sensor relationship is consistent
        with the rule. Low (0.0) when a physics violation is detected.

        For non-involved channels (temp, pressure, humidity, gas), always
        returns 1.0 (no rule defined for them).

        Must be called AFTER ``record_window()`` has been called for the
        current window. The value returned is the one cached by record_window.

        Args:
            channel: channel name (must be one of CHANNELS).

        Returns:
            k value in [0, 1].

        Raises:
            ValueError: if channel is unknown.
        """
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}; must be one of {CHANNELS}")
        return self._k[channel]

    # ------------------------------------------------------------------
    # Introspection (test / debug)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, float]:
        """Return a copy of the current k values keyed by channel name."""
        return dict(self._k)
