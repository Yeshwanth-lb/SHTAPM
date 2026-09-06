"""Axis (i) proxy-based U06 decision-quality rate summary -- pure,
additive, opt-in. See ``project-state/DECISIONS.md``'s "U06 -- Operational
Definitions Proposal" (sections A-F) for the definitions this module
implements EXACTLY, and its "U06 -- RL REWARD SHAPING SPECIFICATION
PROPOSAL" for U06's own still-fully-open status.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

SCOPE -- AXIS (i) ONLY: the already-proposed, proxy-based (``safety_status``/
``requested_action`` only) false-isolation and missed-fault rates. This
module does NOT implement:
  - axis (ii), tracker-vs-injection agreement (does ``safety_status`` agree
    with the real injection ground truth), or
  - axis (iii), ground-truth-anchored rates (redefining false isolation /
    missed fault directly against injection labels instead of against
    ``safety_status``).
Both remain unimplemented, open proposals -- see the "U06 comparison
implementation" scoping review that preceded this increment. This module
reads only the gate-decision-derived fields already on
``edge.eval.rl_baseline_eval.TransitionRecord`` (``safety_status``,
``requested_action``, ``approved_action``, ``policy_status``) -- it never
touches the injection-ground-truth field that same record separately
carries, and never imports anything from the injection-framework package.

PURE FUNCTION, NO STATE: ``summarize_episode_rates()`` takes an existing,
already-computed ``edge.eval.rl_baseline_eval.EpisodeRecord`` and returns a
new ``EpisodeRateSummary`` -- it does not modify ``EpisodeRecord``,
``TransitionRecord``, or any of their fields, and does not call the
environment, gate, reward, or policy modules. It reads ``record``/
``record.transitions`` only.

DEFINITIONS (verbatim from ``DECISIONS.md``'s sections A-C):
  false isolation: ``safety_status == "nominal"`` and ``requested_action``
    is ``RLAction.isolate`` or ``RLAction.reduce_weight``.
  missed critical fault: ``safety_status == "isolation_active"`` and
    ``requested_action`` is ``RLAction.continue_``.
  Both are counted by REQUESTED action, never approved action -- matching
  ``edge/rl/reward.py``'s own existing anti-gate-exploitation choice.
  Denominators are OPPORTUNITY counts (section C), never total step
  counts:
    false-isolation denominator: ``"nominal"`` steps with a non-``None``
      requested action.
    missed-fault denominator: ``"isolation_active"`` steps.
  A zero-denominator scenario/episode reports ``rate=None``, never
  ``0.0`` -- section C's own "misrepresent no opportunity as never
  failed" rationale. ``TransitionRecord.requested_action``/
  ``approved_action`` are already-extracted ``RLAction.value`` strings
  (e.g. ``RLAction.continue_.value == "continue"``, NOT the Python
  identifier ``"continue_"``) -- this module compares against
  ``RLAction.<member>.value`` directly, never a hand-typed literal, to
  avoid exactly that mismatch.

NOT EXCLUDED, ONLY SEPARATELY REPORTED (section F): safe_stop requests,
fallback/unvalidated ``policy_status``, and world-inert approved actions
are NOT subtracted from the opportunity denominators above -- section F's
own text states false-isolation/missed-fault definitions "still evaluate
the requester's intent on these steps," and warns that a policy which
always safe-stops would otherwise show a misleadingly clean rate if such
steps were silently excluded rather than counted as an opportunity that
did not trigger the numerator condition. Instead, each is reported as its
own breakdown field alongside the rate, exactly as section F requires:
``safe_stop_request_count`` (overall, not opportunity-scoped -- a request
for the maximally conservative action is never itself a false isolation or
missed fault, by construction, since it can never equal ``isolate``/
``reduce_weight``/``continue_``), ``policy_status_breakdown`` (a count per
``policy_status`` value across every transition in the episode), and two
world-inert-approved-action counts, each scoped to its own opportunity
denominator (per section F's own "opportunity-steps with a world-inert
approved action" wording). Early termination is represented via the
passed-through ``step_count``/``termination_cause``.

NO THRESHOLD, NO VERDICT, NO REAL-WORLD CLAIM: this module computes counts
and ratios only. It does not choose, suggest, or imply any acceptable
rate; does not compare against real hardware or real-world data; and does
not claim validation, safety, or production readiness for any scenario or
result. U06 (``project-state/DECISIONS.md``) remains fully open -- nothing
here resolves or partially resolves it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

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
class EpisodeRateSummary:
    """Axis (i) proxy-based rate summary for one ``EpisodeRecord`` -- see
    module docstring. Every count/rate here is simulation-only and carries
    no acceptable-threshold, validation, safety, or production-readiness
    claim.

    ``false_isolation_rate``/``missed_fault_rate`` are ``None`` iff their
    own denominator is ``0`` -- never ``0.0`` for a zero-opportunity
    episode (see module docstring's DEFINITIONS section).
    """

    scenario_name: str
    baseline_name: str
    step_count: int
    termination_cause: str

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

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def summarize_episode_rates(record: EpisodeRecord) -> EpisodeRateSummary:
    """Compute axis (i)'s proxy-based false-isolation/missed-fault rate
    summary for one ``EpisodeRecord`` -- see module docstring's
    DEFINITIONS. Pure: reads ``record``/``record.transitions`` only, never
    mutates either, and constructs no new environment/gate/reward/policy
    object.
    """
    false_isolation_denominator = 0
    false_isolation_numerator = 0
    false_isolation_world_inert = 0

    missed_fault_denominator = 0
    missed_fault_numerator = 0
    missed_fault_world_inert = 0

    safe_stop_request_count = 0
    policy_status_counter: Counter[str] = Counter()

    for t in record.transitions:
        policy_status_counter[t.policy_status] += 1

        if t.requested_action == _SAFE_STOP_REQUESTED_ACTION:
            safe_stop_request_count += 1

        if t.safety_status == "nominal" and t.requested_action is not None:
            false_isolation_denominator += 1
            if t.requested_action in _FALSE_ISOLATION_REQUESTED_ACTIONS:
                false_isolation_numerator += 1
            if t.approved_action in _WORLD_INERT_APPROVED_ACTIONS:
                false_isolation_world_inert += 1

        if t.safety_status == "isolation_active":
            missed_fault_denominator += 1
            if t.requested_action == _MISSED_FAULT_REQUESTED_ACTION:
                missed_fault_numerator += 1
            if t.approved_action in _WORLD_INERT_APPROVED_ACTIONS:
                missed_fault_world_inert += 1

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

    return EpisodeRateSummary(
        scenario_name=record.scenario_name,
        baseline_name=record.baseline_name,
        step_count=record.step_count,
        termination_cause=record.termination_cause,
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
    )
