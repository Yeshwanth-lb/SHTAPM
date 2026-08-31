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
    substitution-time proxy. The elapsed-time -> uncertainty scaling formula
    remains a required, never-defaulted constructor argument (D019, open).
self_heal
    ``SelfHealOrchestrator`` -- wires the above together with D018's
    behavioral rules (recovery at TRUSTED_MIN, 60-second substitution
    expiry, cycle sequencing). divergence_threshold and uncertainty_cap are
    required constructor arguments with no default (U05, data-gated).
"""

from edge.pipeline.divergence import DivergenceScorer
from edge.pipeline.self_heal import (
    SUBSTITUTION_MAX_SECONDS_DEFAULT,
    EscalationReason,
    SelfHealAlert,
    SelfHealOrchestrator,
    SelfHealOutcome,
)
from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy, ScalingFn, UncertaintyProxy

__all__ = [
    "SUBSTITUTION_MAX_SECONDS_DEFAULT",
    "DivergenceScorer",
    "ElapsedTimeUncertaintyProxy",
    "EscalationReason",
    "ScalingFn",
    "SelfHealAlert",
    "SelfHealOrchestrator",
    "SelfHealOutcome",
    "UncertaintyProxy",
]
