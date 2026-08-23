"""Edge trust engine (P2 - Beta-reputation foundation).

Modules
-------
beta
    Signal-agnostic Beta-reputation core: consumes per-window evidence ``g``
    and evolves the trust score (U01 foundation).
engine
    Per-channel TrustEngine wrapping BetaState; SignalProvider seam for
    injecting (c, k, h) without coupling to their definitions.
h_reliability
    Historical-reliability signal provider ``h`` (D009, approved 2026-08-23):
    per-channel slow EMA (GAMMA=0.95, H_INIT=1.0) of binary healthy/unhealthy
    window outcomes.

Still undecided (see ``project-state/DECISIONS.md``)
    - lambda=0.7 forgetting factor -- PENDING U01 approval.
    - consistency ``c`` signal definition -- UNDECIDED (U01).
    - cross-sensor correlation ``k`` signal definition -- UNDECIDED (U02).
    - ChannelFlagPolicy (outcome source for h in production) -- UNDECIDED.
"""

from edge.trust.h_reliability import HReliabilityProvider

__all__ = ["HReliabilityProvider"]
