"""Divergence scorer: fit-time z-score of twin-vs-raw residual (P3 · D018 pt.1).

Implements ONLY the divergence *computation form* D018 already decided -- a
fit-time z-score-based magnitude, reusing the same fit-on-clean-baseline-
mean/std discipline already used by ConsistencyProvider/TrendSignPhysicsRule.
No numeric divergence_threshold is chosen here, or anywhere in this slice
(U05, data-gated) -- callers compare the returned score against their own
required threshold parameter (see edge/pipeline/self_heal.py).

Operates on precomputed (reconstruction - raw) residuals, not on Window or
the twin directly, keeping it independently testable and decoupled from
whatever reconstruction algorithm eventually supplies those residuals.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.schemas.contracts import CHANNELS


class DivergenceScorer:
    """Per-channel divergence z-score from a fitted clean-baseline residual
    distribution. Must be fit() for a channel before score() is called for
    it."""

    def __init__(self) -> None:
        self._train_mean: dict[str, float] = {}
        self._train_std: dict[str, float] = {}

    @property
    def fitted(self) -> bool:
        """True once fit() has populated at least one channel."""
        return bool(self._train_mean)

    def fit(self, residuals_by_channel: Mapping[str, Sequence[float]]) -> None:
        """Fit per-channel mean/std of the (reconstruction - raw) residual
        from clean-baseline data (same fit-only-on-clean discipline as
        ConsistencyProvider/TrendSignPhysicsRule -- no attack-labeled
        leakage). Channels not present in ``residuals_by_channel`` remain
        unfitted; a later fit() call adds/overwrites only the channels it
        names.

        Args:
            residuals_by_channel: channel -> sequence of residuals observed
                under clean-baseline conditions.

        Raises:
            ValueError: if empty, if a channel's residual sequence is empty,
                or an unknown channel is given.
        """
        if not residuals_by_channel:
            raise ValueError("fit() requires at least one channel's residuals")
        for ch, residuals in residuals_by_channel.items():
            if ch not in CHANNELS:
                raise ValueError(f"unknown channel {ch!r}; must be one of {CHANNELS}")
            values = list(residuals)
            if not values:
                raise ValueError(f"fit() requires at least one residual for channel {ch!r}")
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / len(values)
            std = var**0.5 or 1e-8  # numerical stability only, not a tunable parameter
            self._train_mean[ch] = mean
            self._train_std[ch] = std

    def score(self, channel: str, residual: float) -> float:
        """Return the z-score magnitude of ``residual`` for ``channel``.

        Raises:
            ValueError: if channel is unknown.
            RuntimeError: if fit() has not been called for this channel.
        """
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}; must be one of {CHANNELS}")
        if channel not in self._train_mean:
            raise RuntimeError(
                f"DivergenceScorer.score({channel!r}) called before fit() for this channel"
            )
        return abs(residual - self._train_mean[channel]) / self._train_std[channel]
