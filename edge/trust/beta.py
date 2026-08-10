"""Signal-agnostic Beta-reputation trust core (P2 · U01 foundation).

Implements ONLY the isolated Beta mathematics approved for U01. It is driven by
a per-window evidence value ``g`` that is **supplied by the caller** — this
module does not define, compute, or assume the consistency (``c``),
cross-sensor correlation (``k``), or historical-reliability (``h``) signals.
Those definitions are UNDECIDED (U01/U02) and live outside this layer.

Documented parameters (PRD FR-T1..T4; Doc05 §05.2 ``thresholds``):
  * model               T = alpha / (alpha + beta)                (FR-T1)
  * priors              alpha0 = beta0 = 1  (uniform Beta, T0 = 0.5)
  * evidence weights    0.4 consistency / 0.3 correlation / 0.3 reliability
                        (Doc05 trust_w_* defaults)                 (FR-T2)
  * bands               Trusted >= 0.7 ; Suspicious 0.4-0.7 ;
                        Malicious < 0.4                            (FR-T3)

Pending-approval parameter (U01 — analyzed, not documented as a spec number):
  * forgetting factor   lambda = 0.7

    Rationale (recorded for the approval trail): starting from full trust, a
    strong-spoof (g = 0) sequence gives T_n = lambda**n, so lambda = 0.7 is the
    largest value with T_3 = 0.343 < 0.4 — it meets the "spoofed sensor reaches
    T < 0.4 within <= 3 windows" target with the least jitter. This value is a
    named constant here; the acceptance tests exercise the g-driven math only,
    NOT any real spoof-detection claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# --- documented constants ---------------------------------------------------
ALPHA0: float = 1.0
BETA0: float = 1.0

# Evidence weights (Doc05 §05.2 trust_w_* defaults; sum to 1.0).
W_CONSISTENCY: float = 0.4
W_CORRELATION: float = 0.3
W_RELIABILITY: float = 0.3

# Classification bands (Doc05 thresholds; FR-T3).
TRUSTED_MIN: float = 0.7
MALICIOUS_MAX: float = 0.4

# Forgetting factor (U01 — pending explicit approval; see module docstring).
DEFAULT_LAMBDA: float = 0.7


class TrustBand(str, Enum):
    """Per-sensor trust classification (FR-T3)."""

    TRUSTED = "trusted"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"


def _check_unit(name: str, x: float) -> float:
    if not (0.0 <= x <= 1.0):
        raise ValueError(f"{name} must be in [0, 1], got {x!r}")
    return x


def combine_g(c: float, k: float, h: float) -> float:
    """Combine the three per-window signals into evidence ``g`` in [0, 1].

    ``g = 0.4*c + 0.3*k + 0.3*h`` using the documented weights (FR-T2). This is
    pure documented arithmetic — it does NOT define what ``c``, ``k``, or ``h``
    mean or how they are measured; the caller supplies them already in [0, 1].
    """
    _check_unit("c", c)
    _check_unit("k", k)
    _check_unit("h", h)
    return W_CONSISTENCY * c + W_CORRELATION * k + W_RELIABILITY * h


def classify(trust: float) -> TrustBand:
    """Map a trust score to its band (FR-T3): >=0.7 Trusted, 0.4-0.7
    Suspicious, <0.4 Malicious."""
    if trust >= TRUSTED_MIN:
        return TrustBand.TRUSTED
    if trust < MALICIOUS_MAX:
        return TrustBand.MALICIOUS
    return TrustBand.SUSPICIOUS


@dataclass
class BetaState:
    """One sensor's Beta-reputation state.

    ``update(g)`` applies the forgetting recursion and returns the new trust
    score. ``g`` is supplied by the caller (signal-agnostic by design).
    """

    alpha: float = ALPHA0
    beta: float = BETA0
    forgetting: float = DEFAULT_LAMBDA

    # Non-init guard so a caller cannot silently build a degenerate state.
    _validated: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not (0.0 < self.forgetting <= 1.0):
            raise ValueError(f"forgetting must be in (0, 1], got {self.forgetting!r}")
        if self.alpha <= 0.0 or self.beta <= 0.0:
            raise ValueError(
                f"alpha and beta must be > 0, got alpha={self.alpha!r}, beta={self.beta!r}"
            )

    @property
    def trust(self) -> float:
        """Current trust score T = alpha / (alpha + beta), in [0, 1]."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def band(self) -> TrustBand:
        """Current classification band."""
        return classify(self.trust)

    def update(self, g: float) -> float:
        """Apply one window of evidence and return the new trust score.

        ``alpha_t = lambda*alpha + g`` ; ``beta_t = lambda*beta + (1 - g)``.
        ``g`` must be in [0, 1] (typically from :func:`combine_g`).
        """
        _check_unit("g", g)
        self.alpha = self.forgetting * self.alpha + g
        self.beta = self.forgetting * self.beta + (1.0 - g)
        return self.trust
