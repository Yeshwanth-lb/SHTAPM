"""RL policy interface + simulation-only baseline policy (FR-RL1/RL2). No
training, learning loop, or reward weights exist yet -- see
``edge/rl/state.py``/``edge/rl/environment.py``/``edge/rl/fallback_gate.py``
for what already exists in this pathway.

PRD basis: FR-RL2 names the action set exactly (already reused verbatim as
``app.schemas.contracts.RLAction`` throughout this pathway). FR-RL4 (fail-
safe deterministic fallback) and U06 (RL reward shaping, fully open in
DECISIONS.md) are the only other relevant entries -- neither specifies a
policy interface shape, a baseline rule set, or any safety threshold. No
DECISIONS.md entry approves any RL policy architecture, so nothing here
claims to BE the eventual FR-RL2 agent -- only a documented, deterministic
stand-in for one.

INTERFACE: ``Policy`` is a ``Protocol`` (mirrors this project's existing
seam style, e.g. ``edge.models.twin.TwinReconstructor``,
``edge.anomaly.pipeline.ChannelFlagPolicy``) -- contract only, no base
class to inherit. ``propose(state)`` accepts ``RLState | None`` (an invalid/
missing state is a real, expected input this interface must handle, not an
error) and returns a ``PolicyDecision``: the proposed ``RLAction`` plus
explicit diagnostics -- ``policy_available``, ``policy_validated``,
``confidence``, ``execution_mode``, ``policy_name``/``policy_version``, and
a human-readable ``reason``. No implementation may claim
``policy_validated=True`` -- nothing in this repo has ever validated an RL
policy, and this module introduces no mechanism to do so.

SIMULATION BASELINE POLICY (``BaselinePolicy``): a deterministic, explicit
rule set over ``RLState``'s trust bands (reusing the existing, already-
approved ``edge.trust.beta.classify``/``TRUSTED_MIN``/``MALICIOUS_MAX`` --
FR-T3 -- not a new threshold) plus ONE new, explicitly-labeled, provisional
health cutoff (``BASELINE_CRITICAL_HEALTH_FIXTURE``) for escalating to
``RLAction.safe_stop``. This is a labeled placeholder standing in for the
FR-RL2 agent during simulation development -- NOT learned intelligence,
NOT research-validated, and NOT presented as such:
``BaselinePolicy.propose()`` always reports ``policy_validated=False`` and
``confidence=None`` (a fixed rule set has no probabilistic confidence to
report -- this is different from, and should not be confused with, an
untrained/low-confidence learned policy's missing score).

FALLBACK INTEGRATION BOUNDARY: neither ``Policy`` nor ``BaselinePolicy``
isolates a channel, actuates anything, publishes anything, or calls the
self-healing adapter/orchestrator -- ``propose()`` returns a plain value,
nothing more. The existing ``edge.rl.fallback_gate.evaluate_rl_action()``
remains the sole authority on whether a proposed action is actually used:
because ``BaselinePolicy`` always reports ``policy_validated=False``, the
gate's own existing rules mean a baseline-proposed action is approved ONLY
when it happens to be ``RLAction.safe_stop`` (the gate's documented carve-
out for the maximally conservative action) -- every other baseline
proposal is replaced by the gate's own deterministic fallback. This is the
correct, intended behavior for an explicitly unvalidated policy, not a
limitation to fix here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.schemas.contracts import RLAction

from edge.rl.state import RLState
from edge.trust.beta import MALICIOUS_MAX, TRUSTED_MIN, TrustBand, classify

EXECUTION_MODE = "simulation"

# Provisional simulation fixture ONLY -- see module docstring. Not a
# DECISIONS.md value; no numeric "critical health" cutoff has ever been
# approved for any purpose in this project. BaselinePolicy.propose()
# requires it as an explicit constructor argument (no default baked into
# the class itself) -- this constant exists solely as a canonical,
# importable value so callers/tests share one copy, mirroring
# ``RL_CONFIDENCE_THRESHOLD_FIXTURE`` (edge/rl/fallback_gate.py).
BASELINE_CRITICAL_HEALTH_FIXTURE = 0.05

BASELINE_POLICY_NAME = "simulation_baseline"
BASELINE_POLICY_VERSION = "0.1.0-unvalidated"


@dataclass(frozen=True)
class PolicyDecision:
    """One ``propose()`` call's output. ``confidence`` is ``None`` unless
    the specific policy implementation has one to report -- never
    fabricated. ``reason`` is a human-readable diagnostic string, not a
    machine-parsed contract."""

    proposed_action: RLAction
    policy_available: bool
    policy_validated: bool
    confidence: float | None
    policy_name: str
    policy_version: str
    reason: str
    execution_mode: str = EXECUTION_MODE


@runtime_checkable
class Policy(Protocol):
    """Injectable RL-policy seam. Contract only -- says nothing about
    architecture, training, or validation status; each implementation
    reports its own via ``PolicyDecision``."""

    def propose(self, state: RLState | None) -> PolicyDecision: ...


class BaselinePolicy:
    """Deterministic, simulation-only stand-in for the FR-RL2 agent -- see
    module docstring's SIMULATION BASELINE POLICY section. Always reports
    ``policy_available=True`` (the rule set is always present -- there is
    no "checkpoint" to be missing) and ``policy_validated=False`` (never
    claims validation).
    """

    def __init__(self, *, critical_health_threshold: float) -> None:
        if not (0.0 <= critical_health_threshold <= 1.0):
            raise ValueError(
                f"critical_health_threshold must be in [0, 1], got {critical_health_threshold}"
            )
        self._critical_health_threshold = critical_health_threshold

    def propose(self, state: RLState | None) -> PolicyDecision:
        if state is None:
            return self._decision(RLAction.safe_stop, "state is unavailable")

        if state.health is not None and state.health <= self._critical_health_threshold:
            return self._decision(
                RLAction.safe_stop,
                f"health {state.health} is at/below the baseline critical threshold "
                f"{self._critical_health_threshold}",
            )

        bands = {ch: classify(value) for ch, value in state.trust.items()}
        malicious = sorted(ch for ch, band in bands.items() if band is TrustBand.MALICIOUS)
        suspicious = sorted(ch for ch, band in bands.items() if band is TrustBand.SUSPICIOUS)

        if malicious:
            return self._decision(
                RLAction.isolate,
                f"channel(s) in malicious trust band (trust < {MALICIOUS_MAX}): {malicious}",
            )
        if suspicious:
            return self._decision(
                RLAction.reduce_weight,
                f"channel(s) in suspicious trust band ({MALICIOUS_MAX} <= trust < "
                f"{TRUSTED_MIN}): {suspicious}",
            )
        if state.anomaly_flag:
            return self._decision(
                RLAction.alert,
                "anomaly flagged with no channel in a degraded trust band",
            )
        return self._decision(RLAction.continue_, "nominal state: no anomaly, all channels trusted")

    def _decision(self, action: RLAction, reason: str) -> PolicyDecision:
        return PolicyDecision(
            proposed_action=action,
            policy_available=True,
            policy_validated=False,
            confidence=None,
            policy_name=BASELINE_POLICY_NAME,
            policy_version=BASELINE_POLICY_VERSION,
            reason=reason,
        )


def band_summary(trust: Mapping[str, float]) -> dict[str, TrustBand]:
    """Convenience: classify every channel in ``trust`` at once (thin
    wrapper over ``edge.trust.beta.classify``, exposed for callers/tests
    that want the same banding ``BaselinePolicy`` uses without duplicating
    it)."""
    return {ch: classify(value) for ch, value in trust.items()}
