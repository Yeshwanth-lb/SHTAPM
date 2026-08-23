"""Historical-reliability signal provider for the trust engine (P2 - D009).

Implements the ``h`` component of ``g = 0.4*c + 0.3*k + 0.3*h`` (FR-T2 /
Doc05 section 05.2 ``trust_w_reliability=0.3``).

Design decision D009 (approved 2026-08-23)::

    h_ch,t = GAMMA * h_ch,t-1 + (1 - GAMMA) * outcome_ch,t

    GAMMA  = 0.95  (approved slow forgetting factor; half-life ~13 windows)
    H_INIT = 1.0   (clean-history prior -- assume reliable until evidence arrives)
    outcome in {0.0, 1.0} -- supplied by the caller as a bool

This module is deliberately **agnostic** about how the outcome was determined:
it does not know about AnomalyResult, ChannelFlagPolicy, Isolation Forest,
consistency (``c``), or cross-sensor correlation (``k``).  The caller supplies
``record_outcome(channel, was_healthy)`` once per window, then the engine
reads ``evaluate(channel)`` via the SignalProvider protocol.

Independence from ``c``
    ``c`` will measure a per-window continuous anomaly residual (present window).
    ``h`` integrates binary past outcomes over a long horizon -- different
    observation type (binary vs. continuous), different timescale (slow vs. fast),
    different object (history vs. present).  No computation is shared.

Independence from ``g`` / ``BetaState``
    ``h`` does not read ``BetaState.alpha``, ``BetaState.beta``, or the combined
    ``g`` value.  It maintains its own scalar state per channel.

Pending items (NOT resolved by this module)
    lambda=0.7 (Beta forgetting factor) -- still PENDING U01 approval.
    ``c`` signal definition -- UNDECIDED (U01).
    ``k`` signal definition -- UNDECIDED (U02).
    ``ChannelFlagPolicy``  -- UNDECIDED (seam).
"""

from __future__ import annotations

from app.schemas.contracts import CHANNELS

# Approved constants (D009 -- 2026-08-23).
GAMMA: float = 0.95   # slow forgetting factor (approved)
H_INIT: float = 1.0   # clean-history prior for every channel


class HReliabilityProvider:
    """Per-channel slow EMA of binary healthy/unhealthy window outcomes.

    Implements the SignalProvider protocol so it can be injected directly into
    ``TrustEngine.update_from_providers``.

    Typical per-window call sequence (managed by the caller, e.g. pipeline)::

        # 1. Record outcome of the window that just completed.
        h_provider.record_outcome(channel, was_healthy)

        # 2. Engine pulls h via evaluate(); h_t reflects outcomes through t-1.
        engine.update_from_providers(c_prov, k_prov, h_provider)

    This causal ordering means ``h_t`` reflects outcomes through window ``t-1``
    (not the current window) when first called after initialization.
    """

    def __init__(self) -> None:
        # One float per frozen channel, initialized to the clean-history prior.
        self._h: dict[str, float] = {ch: H_INIT for ch in CHANNELS}

    # ------------------------------------------------------------------
    # SignalProvider protocol
    # ------------------------------------------------------------------

    def evaluate(self, channel: str) -> float:
        """Return the current h value for ``channel`` in [0, 1].

        Raises ``ValueError`` for an unknown channel (consistent with the
        ``TrustEngine._require_channel`` convention).
        """
        return self._require_channel(channel)

    # ------------------------------------------------------------------
    # State update
    # ------------------------------------------------------------------

    def record_outcome(self, channel: str, was_healthy: bool) -> None:
        """Apply one window outcome for ``channel`` and update its EMA.

        ``was_healthy=True``  -> outcome 1.0 (h drifts toward 1.0 slowly).
        ``was_healthy=False`` -> outcome 0.0 (h decays by factor GAMMA=0.95).

        Only ``channel`` is modified; all other channels are untouched.

        Raises ``ValueError`` for an unknown channel.
        """
        self._require_channel(channel)  # validate before mutating
        outcome = 1.0 if was_healthy else 0.0
        self._h[channel] = GAMMA * self._h[channel] + (1.0 - GAMMA) * outcome

    # ------------------------------------------------------------------
    # Introspection (test / debug)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, float]:
        """Return a copy of the current h values keyed by channel name."""
        return dict(self._h)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_channel(self, channel: str) -> float:
        """Return the h value for ``channel``, or raise ``ValueError``."""
        try:
            return self._h[channel]
        except KeyError:
            raise ValueError(
                f"unknown channel {channel!r}; must be one of {CHANNELS}"
            ) from None
