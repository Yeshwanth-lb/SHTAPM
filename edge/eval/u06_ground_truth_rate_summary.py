"""Axis (iii) coarse, ground-truth-anchored U06 decision-quality rate
summary -- pure, additive, opt-in. See ``project-state/DECISIONS.md``'s
"U06 -- Operational Definitions Proposal" (sections A-C) for the proxy-
based rate definitions this module deliberately does NOT use, and the
axis (iii) scoping review that preceded this increment for the full
rationale behind every design choice below.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

SCOPE -- COARSE, GROUND-TRUTH-ANCHORED, AXIS (iii) ONLY: this module
redefines false isolation / missed fault directly against
``bool(active_injection_labels)`` (synthetic injection ground truth)
INSTEAD OF against ``safety_status`` (the deterministic tracker's own
proxy, used by axis (i) -- ``edge.eval.u06_rate_summary``, unmodified by
this module). This module does NOT:
  - match the SPECIFIC injected channel against anything (``RLAction.
    isolate`` itself carries no channel parameter -- see the axis (iii)
    scoping review's own correction of this point);
  - widen ``TransitionRecord.active_injection_labels``'s shape or add any
    tracked-channel field;
  - implement axis (i) (unmodified, separate module) or axis (ii) (tracker-
    vs-injection agreement -- ``edge.eval.u06_tracker_agreement``,
    unmodified by this module);
  - introduce any new threshold, verdict, or acceptability rule.
This module reads only ``EpisodeRecord``/``TransitionRecord``'s existing
``requested_action``, ``approved_action``, ``policy_status``, and
injection-ground-truth fields; it never imports anything from the
injection-framework package and never touches the environment, gate,
reward, or policy modules directly.

UNIT OF COMPARISON -- EVERY STEP, NOT FILTERED BY ``transition_consumed``:
unlike axis (ii) (which compares FRAME-level ground truth against FRAME-
level tracker state, and must exclude ``transition_consumed=False`` steps
to avoid scoring the same already-processed frame twice), axis (iii)
compares a DECISION (``requested_action``) against ground truth -- exactly
like axis (i) does. Every step, including a ``safe_stop`` no-op step, is a
genuine, distinct policy decision even when the underlying environment
state repeats, so none are filtered out here.

SAFE_STOP CANNOT TRIGGER EITHER NUMERATOR, BY CONSTRUCTION: a
``transition_consumed=False`` step can only occur when
``gate_decision.approved_action is RLAction.safe_stop``, which itself (per
``edge/rl/fallback_gate.py``'s own carve-out logic, and
``SHTAPMSimulationEnvironment`` always passing ``already_safe_stopped=
False``) can only happen when ``requested_action is RLAction.safe_stop``
too. Since neither of this module's two numerator conditions can ever
equal ``RLAction.safe_stop.value``, a safe_stop-requesting step can never
itself count as a ground-truth false isolation or a ground-truth missed
fault -- it remains in the documented denominators (per section F's own
"not excluded, only separately reported" convention, reused unchanged from
axis (i)) and is additionally counted via ``safe_stop_request_count``.

DEFINITIONS (ground-truth-anchored, NOT the axis (i) proxy definitions):
  ground-truth false isolation: ``requested_action`` is ``RLAction.
    isolate`` or ``RLAction.reduce_weight`` AND no injection was active
    (``active_injection_labels`` is empty).
  ground-truth missed fault: ``requested_action`` is ``RLAction.continue_``
    AND an injection was active (``active_injection_labels`` is non-empty).
  Denominators reuse axis (i)'s own opportunity-denominator convention,
  substituting ground truth for the ``safety_status`` proxy:
    false-isolation denominator: no injection active, with a non-``None``
      requested action.
    missed-fault denominator: an injection active.
  A zero-denominator episode reports ``rate=None``, never ``0.0`` -- same
  rationale as axis (i)/(ii). ``TransitionRecord.requested_action`` is
  already an extracted ``RLAction.value`` string (e.g.
  ``RLAction.continue_.value == "continue"``) -- this module compares
  against ``RLAction.<member>.value`` directly, never a hand-typed
  literal, matching axis (i)'s own safeguard against that mismatch.

REQUIRED METHODOLOGICAL DISCLAIMERS (must be read before interpreting any
count/rate this module produces):
  1. An active injection label means an injection was ATTEMPTED at that
     step -- it does not mean the injection was DETECTABLE by this
     pipeline's own trust/anomaly logic.
  2. More fundamentally: an injection may leave NO trace at all in the
     policy's own observed state. ``edge.rl.state.RLState`` -- the ONLY
     input any policy in this pathway ever receives -- carries ``health``,
     ``anomaly_flag``, per-channel ``trust``, and ``failure_eta``; it
     carries no injection-ground-truth field of any kind. A policy has no
     structural path to observe ``active_injection_labels`` directly.
  3. Consequently, a ground-truth missed-fault count is NOT proof of a
     policy decision failure -- it may equally reflect that no signal
     reaching the policy's own state representation could have revealed
     the injection at all, a limit of the state representation (FR-RL1),
     not of any policy's competence.
  4. Injection types deliberately engineered to evade detection --
     ``AdaptiveStealthFDI`` in particular (see ``edge/injection/
     injections.py``'s own docstring) -- require especially cautious
     interpretation of any missed-fault count attributed to them: a
     "miss" may be the tracker/policy behaving exactly as any reasonable
     system would against a deliberately-evasive input, not a defect.
  5. Every count and rate this module produces describes SIMULATION-ONLY
     tracker/policy behavior on synthetic, manufactured trajectories. None
     of it is, or should be read as, a real-world accuracy, safety,
     validation, or production-readiness claim, an acceptable threshold,
     or a verdict of any kind. U06 (``project-state/DECISIONS.md``)
     remains fully open -- nothing here resolves or partially resolves it.

PER-INJECTION-TYPE ATTRIBUTION: an observation whose
``active_injection_labels`` names more than one injection type is
attributed to EACH of its active types for the missed-fault breakdown
(mirroring axis (ii)'s own PER-INJECTION-TYPE ATTRIBUTION convention) --
per-type counts can therefore sum to more than the aggregate missed-fault
denominator when multiple injections are simultaneously active. Missed-
fault results are NEVER pooled across injection types into one unqualified
number -- see disclaimer 4 above for why that would be actively
misleading.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.schemas.contracts import RLAction

from edge.eval.rl_baseline_eval import EpisodeRecord

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"

_FALSE_ISOLATION_REQUESTED_ACTIONS = frozenset(
    {RLAction.isolate.value, RLAction.reduce_weight.value}
)
_MISSED_FAULT_REQUESTED_ACTION = RLAction.continue_.value
_SAFE_STOP_REQUESTED_ACTION = RLAction.safe_stop.value
_WORLD_INERT_APPROVED_ACTIONS = frozenset(
    {RLAction.continue_.value, RLAction.alert.value, RLAction.reduce_weight.value}
)


@dataclass(frozen=True)
class InjectionTypeMissedFaultBreakdown:
    """Ground-truth missed-fault counts scoped to observations where this
    specific injection type was among the active labels -- see module
    docstring's PER-INJECTION-TYPE ATTRIBUTION section. Every observation
    counted here had this injection type active by definition, so only
    the missed-fault outcome is meaningful (a false isolation cannot occur
    when an injection is active, by this module's own definitions)."""

    injection_type: str
    observation_count: int
    missed_fault_count: int
    missed_fault_rate: float | None  # None iff observation_count == 0


@dataclass(frozen=True)
class NoInjectionFalseIsolationBreakdown:
    """A convenience mirror of the summary's own top-level false-isolation
    fields, scoped explicitly to the no-injection population -- reported
    as its own field so the clean/no-injection case is never conflated
    with the per-injection-type missed-fault breakdowns below."""

    observation_count: int
    false_isolation_count: int
    false_isolation_rate: float | None  # None iff observation_count == 0


@dataclass(frozen=True)
class GroundTruthRateSummary:
    """Axis (iii) coarse, ground-truth-anchored rate summary for one
    ``EpisodeRecord`` -- see module docstring, especially its REQUIRED
    METHODOLOGICAL DISCLAIMERS section. Every count/rate here is
    simulation-only and carries no acceptable-threshold, validation,
    safety, or production-readiness claim.

    ``false_isolation_rate``/``missed_fault_rate`` are ``None`` iff their
    own denominator is ``0``.
    """

    scenario_name: str
    baseline_name: str

    false_isolation_numerator: int
    false_isolation_denominator: int
    false_isolation_rate: float | None

    missed_fault_numerator: int
    missed_fault_denominator: int
    missed_fault_rate: float | None

    safe_stop_request_count: int
    policy_status_breakdown: dict[str, int]
    world_inert_approved_action_count_in_false_isolation_denominator: int
    world_inert_approved_action_count_in_missed_fault_denominator: int

    per_injection_type: dict[str, InjectionTypeMissedFaultBreakdown] = field(
        default_factory=dict
    )
    no_injection: NoInjectionFalseIsolationBreakdown | None = None

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def summarize_ground_truth_rates(record: EpisodeRecord) -> GroundTruthRateSummary:
    """Compute axis (iii)'s coarse, ground-truth-anchored false-isolation/
    missed-fault rate summary for one ``EpisodeRecord`` -- see module
    docstring's DEFINITIONS and REQUIRED METHODOLOGICAL DISCLAIMERS. Pure:
    reads ``record``/``record.transitions`` only, never mutates either,
    and constructs no new environment/gate/reward/policy object. Every
    transition in ``record.transitions`` is counted -- no
    ``transition_consumed`` filtering (see module docstring's UNIT OF
    COMPARISON section).
    """
    false_isolation_denominator = 0
    false_isolation_numerator = 0
    false_isolation_world_inert = 0

    missed_fault_denominator = 0
    missed_fault_numerator = 0
    missed_fault_world_inert = 0

    safe_stop_request_count = 0
    policy_status_counter: Counter[str] = Counter()

    per_type_observations: Counter[str] = Counter()
    per_type_missed: Counter[str] = Counter()

    for t in record.transitions:
        policy_status_counter[t.policy_status] += 1

        if t.requested_action == _SAFE_STOP_REQUESTED_ACTION:
            safe_stop_request_count += 1

        injected = bool(t.active_injection_labels)

        if not injected and t.requested_action is not None:
            false_isolation_denominator += 1
            if t.requested_action in _FALSE_ISOLATION_REQUESTED_ACTIONS:
                false_isolation_numerator += 1
            if t.approved_action in _WORLD_INERT_APPROVED_ACTIONS:
                false_isolation_world_inert += 1

        if injected:
            missed_fault_denominator += 1
            missed = t.requested_action == _MISSED_FAULT_REQUESTED_ACTION
            if missed:
                missed_fault_numerator += 1
            if t.approved_action in _WORLD_INERT_APPROVED_ACTIONS:
                missed_fault_world_inert += 1
            for injection_type in t.active_injection_labels:
                per_type_observations[injection_type] += 1
                if missed:
                    per_type_missed[injection_type] += 1

    false_isolation_rate = (
        false_isolation_numerator / false_isolation_denominator
        if false_isolation_denominator > 0
        else None
    )
    missed_fault_rate = (
        missed_fault_numerator / missed_fault_denominator
        if missed_fault_denominator > 0
        else None
    )

    per_injection_type: dict[str, InjectionTypeMissedFaultBreakdown] = {}
    for injection_type in sorted(per_type_observations):
        obs_count = per_type_observations[injection_type]
        missed_count = per_type_missed[injection_type]
        per_injection_type[injection_type] = InjectionTypeMissedFaultBreakdown(
            injection_type=injection_type,
            observation_count=obs_count,
            missed_fault_count=missed_count,
            missed_fault_rate=(missed_count / obs_count if obs_count > 0 else None),
        )

    no_injection = NoInjectionFalseIsolationBreakdown(
        observation_count=false_isolation_denominator,
        false_isolation_count=false_isolation_numerator,
        false_isolation_rate=false_isolation_rate,
    )

    return GroundTruthRateSummary(
        scenario_name=record.scenario_name,
        baseline_name=record.baseline_name,
        false_isolation_numerator=false_isolation_numerator,
        false_isolation_denominator=false_isolation_denominator,
        false_isolation_rate=false_isolation_rate,
        missed_fault_numerator=missed_fault_numerator,
        missed_fault_denominator=missed_fault_denominator,
        missed_fault_rate=missed_fault_rate,
        safe_stop_request_count=safe_stop_request_count,
        policy_status_breakdown=dict(policy_status_counter),
        world_inert_approved_action_count_in_false_isolation_denominator=(
            false_isolation_world_inert
        ),
        world_inert_approved_action_count_in_missed_fault_denominator=missed_fault_world_inert,
        per_injection_type=per_injection_type,
        no_injection=no_injection,
    )
