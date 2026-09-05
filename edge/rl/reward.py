"""RL reward contract + calculation (FR-RL3) -- simulation-only, no
training loop, no approved weights. See ``edge/rl/state.py``,
``edge/rl/environment.py``, ``edge/rl/fallback_gate.py``,
``edge/rl/policy.py`` for the rest of this pathway; nothing here modifies
any of them.

PRD FR-RL3: "The agent's reward shall penalize false isolation, missed
critical faults, and downtime." U06 (RL reward shaping + acceptable
false-isolation rate) is fully open in DECISIONS.md -- no entry specifies
component weights, relative importance, or a reward formula. This module
therefore defines the reward's SHAPE (what components exist and how each
is computed from already-existing signals) without inventing a final
answer to U06: every numeric magnitude below is an explicit, named,
provisional simulation fixture, distinct in name and value from every
other project fixture (``UNCERTAINTY_CAP_D020``,
``SYNTHETIC_HEALTH_WARNING_THRESHOLD``/``..._CRITICAL_THRESHOLD``,
``RL_CONFIDENCE_THRESHOLD_FIXTURE``, ``BASELINE_CRITICAL_HEALTH_
FIXTURE``) -- reusing any of those here would misapply a value approved
for an unrelated purpose.

REUSE, NOT RE-DERIVATION: ``compute_reward()`` takes an already-computed
``edge.rl.fallback_gate.GateDecision`` (never re-runs isolation/trust-band
logic itself) plus the previous/next ``RLState``. It evaluates components
against ``gate_decision.requested_action`` (what the policy actually
wanted), not ``approved_action`` (what the gate let happen) -- this is a
deliberate safety-shielding choice: if reward were computed only against
the gate-approved action, a policy could learn to request anything and
rely on the gate to always produce a safe outcome, receiving no signal to
avoid requesting unsafe actions in the first place. ``approved_action``
and ``fallback_used`` are still carried on ``RewardResult`` for
diagnostics.

COMPONENTS (map directly to the seven objectives named in this increment's
own scope, and to FR-RL3's three named penalties -- see each field's own
comment in ``RewardComponents``): ``health_maintenance``,
``anomaly_impact``, ``trust_preservation``, ``isolation_appropriateness``
(covers FR-RL3's "false isolation" AND "missed critical faults" as one
signed value -- see its own docstring), ``unsafe_action_penalty``,
``recovery_stabilization``, ``safe_stop_behavior`` (covers FR-RL3's
"downtime" via its unnecessary-stop penalty).

WEIGHTS ARE OPTIONAL AND NEVER DEFAULTED: ``compute_reward(weights=None)``
(the default) returns every component but ``total=None`` --
``reward_policy_status="unweighted"`` -- honestly reflecting that U06 has
not resolved how these components combine. Passing an explicit
``RewardWeights`` (e.g. the named ``SIMULATION_REWARD_WEIGHTS_FIXTURE``, a
uniform 1.0-per-component placeholder, NOT a tuned or research value)
computes ``total`` and sets ``reward_policy_status=
"simulation_fixture_weighted"``. No weight is ever assumed silently.

SIDE-EFFECT FREE: this module isolates nothing, actuates nothing,
publishes nothing, and writes nothing -- it only reads the already-
computed ``RLState``/``GateDecision`` values it is given and returns a new
``RewardResult``.

SMALLEST COMPATIBLE ENVIRONMENT CHANGE (documented, NOT performed here):
``edge/rl/environment.py``'s ``step()`` currently never runs the requested
action through ``edge.rl.fallback_gate.evaluate_rl_action()`` at all (no
``GateDecision`` exists in that module yet) and returns a placeholder
``RewardSignal()`` with ``total=None``. Wiring this module in would mean:
(1) ``step()`` calls ``evaluate_rl_action()`` with the requested action and
its own already-available ``isolation_status``/state, (2) calls
``compute_reward(previous_state=<state before this tick>, gate_decision=...,
next_state=<state this tick>)`` instead of constructing a bare
``RewardSignal()``, (3) ``EnvironmentStepResult.reward`` becomes a
``RewardResult`` instead of a ``RewardSignal``. That change is deliberately
NOT made in this increment (composition-root-adjacent wiring is out of
scope) -- see the report accompanying this module for the full rationale.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.contracts import RLAction

from edge.rl.fallback_gate import GateDecision
from edge.rl.state import RLState

EXECUTION_MODE = "simulation"

# ---- Provisional simulation fixtures ONLY -- see module docstring -------
# A single shared unit magnitude for every penalty/reward term below: using
# one undifferentiated value, rather than distinct hand-picked numbers per
# component, avoids implying that any relative importance between
# components has been decided (that is exactly U06's open question).
PENALTY_MAGNITUDE_FIXTURE = 1.0
REWARD_MAGNITUDE_FIXTURE = 1.0


@dataclass(frozen=True)
class RewardComponents:
    """One transition's reward, broken out by objective. Every field is
    always computed (never ``None``) -- an unavailable state/value makes a
    component neutral (``0.0``), never fabricated in either direction."""

    health_maintenance: float
    """Maintaining system health: next_state.health directly ([0, 1],
    higher is better). 0.0 if next_state or its health is unavailable."""

    anomaly_impact: float
    """Reducing anomaly impact: -PENALTY_MAGNITUDE_FIXTURE if next_state's
    anomaly_flag is True, else 0.0. 0.0 if next_state is unavailable."""

    trust_preservation: float
    """Preserving trusted channels: mean of next_state.trust.values()
    ([0, 1], higher is better). 0.0 if next_state is unavailable."""

    isolation_appropriateness: float
    """FR-RL3's "false isolation" and "missed critical faults", as one
    signed value: -PENALTY_MAGNITUDE_FIXTURE if the REQUESTED action was
    isolate/reduce_weight while the deterministic safety_status was
    "nominal" (false isolation); -PENALTY_MAGNITUDE_FIXTURE if it was
    continue_ while safety_status was "isolation_active" (missed fault);
    0.0 otherwise."""

    unsafe_action_penalty: float
    """Avoiding unsafe actions: -PENALTY_MAGNITUDE_FIXTURE if the gate's
    own hard safety constraints were violated by the request (system
    already safe-stopped but something else was requested, or continue_
    was requested while a channel remains a tracked isolation candidate);
    0.0 otherwise. Deliberately narrower than "fallback_used" in general --
    a fallback caused only by policy unavailability/low confidence is not,
    by itself, an unsafe ACTION."""

    recovery_stabilization: float
    """Successful recovery or stabilization: next_state.health -
    previous_state.health (positive = improving). 0.0 if either state or
    either health value is unavailable."""

    safe_stop_behavior: float
    """FR-RL3's "downtime", plus rewarding correct safe-stop:
    +REWARD_MAGNITUDE_FIXTURE if safe_stop was requested while
    safety_status was NOT "nominal" (a warranted stop); -PENALTY_MAGNITUDE_
    FIXTURE if safe_stop was requested while safety_status WAS "nominal"
    (unwarranted downtime); 0.0 if safe_stop was not requested."""


@dataclass(frozen=True)
class RewardWeights:
    """Per-component weights for combining ``RewardComponents`` into a
    single ``total``. Every field is REQUIRED -- no default anywhere in
    this class or in ``compute_reward`` -- so a total is only ever
    computed from weights a caller explicitly chose. See
    ``SIMULATION_REWARD_WEIGHTS_FIXTURE`` for the one named, importable,
    explicitly-non-final example."""

    health_maintenance: float
    anomaly_impact: float
    trust_preservation: float
    isolation_appropriateness: float
    unsafe_action_penalty: float
    recovery_stabilization: float
    safe_stop_behavior: float


# A uniform 1.0-per-component placeholder -- explicitly NOT a tuned or
# research-derived weighting (U06 remains open). Distinct in name and
# value from every other fixture in this project (see module docstring).
SIMULATION_REWARD_WEIGHTS_FIXTURE = RewardWeights(
    health_maintenance=1.0,
    anomaly_impact=1.0,
    trust_preservation=1.0,
    isolation_appropriateness=1.0,
    unsafe_action_penalty=1.0,
    recovery_stabilization=1.0,
    safe_stop_behavior=1.0,
)


@dataclass(frozen=True)
class RewardResult:
    """One transition's full reward accounting.

    ``total`` is ``None`` unless ``weights`` was supplied to
    ``compute_reward`` -- see module docstring. ``reward_policy_status`` is
    ``"unweighted"`` or ``"simulation_fixture_weighted"``, never a claim
    that U06 has been resolved. ``simulation_only`` is always ``True`` --
    this module has no path to computing a real-world reward.
    """

    total: float | None
    components: RewardComponents
    requested_action: RLAction | None
    approved_action: RLAction
    fallback_used: bool
    previous_state: RLState | None
    next_state: RLState | None
    execution_mode: str = EXECUTION_MODE
    reward_policy_status: str = "unweighted"
    simulation_only: bool = True


def _health_or_none(state: RLState | None) -> float | None:
    if state is None:
        return None
    return state.health


def _compute_components(
    previous_state: RLState | None,
    gate_decision: GateDecision,
    next_state: RLState | None,
) -> RewardComponents:
    requested = gate_decision.requested_action
    safety_status = gate_decision.safety_status

    next_health = _health_or_none(next_state)
    health_maintenance = next_health if next_health is not None else 0.0

    anomaly_impact = 0.0
    if next_state is not None and next_state.anomaly_flag:
        anomaly_impact = -PENALTY_MAGNITUDE_FIXTURE

    trust_preservation = 0.0
    if next_state is not None and next_state.trust:
        trust_preservation = sum(next_state.trust.values()) / len(next_state.trust)

    isolation_appropriateness = 0.0
    if requested in (RLAction.isolate, RLAction.reduce_weight) and safety_status == "nominal":
        isolation_appropriateness = -PENALTY_MAGNITUDE_FIXTURE
    elif requested is RLAction.continue_ and safety_status == "isolation_active":
        isolation_appropriateness = -PENALTY_MAGNITUDE_FIXTURE

    unsafe_action_penalty = 0.0
    already_safe_stopped_violation = (
        safety_status == "safe_stop_active" and requested is not RLAction.safe_stop
    )
    tracked_continue_violation = (
        safety_status == "isolation_active" and requested is RLAction.continue_
    )
    if already_safe_stopped_violation or tracked_continue_violation:
        unsafe_action_penalty = -PENALTY_MAGNITUDE_FIXTURE

    recovery_stabilization = 0.0
    previous_health = _health_or_none(previous_state)
    if previous_health is not None and next_health is not None:
        recovery_stabilization = next_health - previous_health

    safe_stop_behavior = 0.0
    if requested is RLAction.safe_stop:
        safe_stop_behavior = (
            REWARD_MAGNITUDE_FIXTURE if safety_status != "nominal" else -PENALTY_MAGNITUDE_FIXTURE
        )

    return RewardComponents(
        health_maintenance=health_maintenance,
        anomaly_impact=anomaly_impact,
        trust_preservation=trust_preservation,
        isolation_appropriateness=isolation_appropriateness,
        unsafe_action_penalty=unsafe_action_penalty,
        recovery_stabilization=recovery_stabilization,
        safe_stop_behavior=safe_stop_behavior,
    )


def _weighted_total(components: RewardComponents, weights: RewardWeights) -> float:
    return (
        components.health_maintenance * weights.health_maintenance
        + components.anomaly_impact * weights.anomaly_impact
        + components.trust_preservation * weights.trust_preservation
        + components.isolation_appropriateness * weights.isolation_appropriateness
        + components.unsafe_action_penalty * weights.unsafe_action_penalty
        + components.recovery_stabilization * weights.recovery_stabilization
        + components.safe_stop_behavior * weights.safe_stop_behavior
    )


def compute_reward(
    *,
    previous_state: RLState | None,
    gate_decision: GateDecision,
    next_state: RLState | None,
    weights: RewardWeights | None = None,
) -> RewardResult:
    """Compute one transition's reward accounting. Never raises for an
    invalid/missing state or action -- those are exactly the conditions
    this function must handle safely (see each ``RewardComponents`` field's
    own docstring for its neutral-value behavior).

    ``weights=None`` (default): every component is still computed, but
    ``total=None`` and ``reward_policy_status="unweighted"`` -- see module
    docstring. Pass ``SIMULATION_REWARD_WEIGHTS_FIXTURE`` (or any other
    explicit ``RewardWeights``) to also compute ``total``.
    """
    components = _compute_components(previous_state, gate_decision, next_state)

    if weights is None:
        total = None
        reward_policy_status = "unweighted"
    else:
        total = _weighted_total(components, weights)
        reward_policy_status = "simulation_fixture_weighted"

    return RewardResult(
        total=total,
        components=components,
        requested_action=gate_decision.requested_action,
        approved_action=gate_decision.approved_action,
        fallback_used=gate_decision.fallback_used,
        previous_state=previous_state,
        next_state=next_state,
        reward_policy_status=reward_policy_status,
    )
