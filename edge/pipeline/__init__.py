"""P3 self-heal orchestration: isolation -> substitution -> divergence
backstop -> Safe Pump-Stop (FR-H1-H4, D016-D019).

Modules
-------
divergence
    ``DivergenceScorer`` -- fit-time z-score of the twin-vs-raw residual
    (D018 pt.1's approved computation form). No numeric divergence_threshold
    is chosen here (U05, data-gated).
uncertainty
    ``ElapsedTimeUncertaintyProxy`` -- D019's deterministic elapsed-
    substitution-time proxy. The elapsed-time -> uncertainty scaling
    formula is D020-approved (``linear_scaling``) but remains a required,
    never-defaulted constructor argument -- the constant is a canonical
    reference only, never wired in automatically.
self_heal
    ``SelfHealOrchestrator`` -- wires the above together with D018's
    behavioral rules (recovery at TRUSTED_MIN, 60-second substitution
    expiry, cycle sequencing). ``uncertainty_cap`` is D020-approved
    (``UNCERTAINTY_CAP_D020`` = 0.8) but remains a required constructor
    argument with no default; ``divergence_threshold`` remains genuinely
    open and data-gated (U05).
"""

from edge.pipeline.divergence import DivergenceScorer
from edge.pipeline.self_heal import (
    SUBSTITUTION_MAX_SECONDS_DEFAULT,
    UNCERTAINTY_CAP_D020,
    EscalationReason,
    SelfHealAlert,
    SelfHealOrchestrator,
    SelfHealOutcome,
)
from edge.pipeline.uncertainty import (
    ElapsedTimeUncertaintyProxy,
    ScalingFn,
    UncertaintyProxy,
    linear_scaling,
)

__all__ = [
    "SUBSTITUTION_MAX_SECONDS_DEFAULT",
    "UNCERTAINTY_CAP_D020",
    "DivergenceScorer",
    "ElapsedTimeUncertaintyProxy",
    "EscalationReason",
    "ScalingFn",
    "SelfHealAlert",
    "SelfHealOrchestrator",
    "SelfHealOutcome",
    "UncertaintyProxy",
    "linear_scaling",
]
