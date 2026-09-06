"""Axis (ii) coarse, presence-only tracker-vs-injection agreement -- pure,
additive, opt-in. See ``project-state/DECISIONS.md``'s "U06 -- Operational
Definitions Proposal" (sections D and G) for the ``safety_status``-is-a-
proxy gap this module investigates, and its "U06 -- RL REWARD SHAPING
SPECIFICATION PROPOSAL" for U06's own still-fully-open status.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

SCOPE -- COARSE, PRESENCE-ONLY, AXIS (ii) ONLY: this module compares
whether ANY injection was active at an observed frame
(``bool(active_injection_labels)``) against whether the deterministic
tracker considered the system ``"isolation_active"`` at that same frame. It
does NOT:
  - match the SPECIFIC injected channel against the SPECIFIC tracked
    channel (a channel-matched comparison would need the tracked-channel
    data ``edge.rl.environment``'s ``EnvironmentStepResult.info
    ["persistent_isolation_tracked_channels"]`` computes but
    ``edge.eval.rl_baseline_eval.TransitionRecord`` does not currently
    carry -- a real, confirmed gap, not addressed here);
  - widen ``TransitionRecord.active_injection_labels``'s shape;
  - add any tracked-channel field to ``TransitionRecord``;
  - implement axis (i) (already implemented separately in
    ``edge.eval.u06_rate_summary``) or axis (iii) (ground-truth-anchored
    decision-quality rates -- a distinct, still-unimplemented proposal).
This module reads only ``EpisodeRecord``/``TransitionRecord``'s existing
``safety_status`` and injection-ground-truth fields; it never imports
anything from the injection-framework package and never touches the
environment, gate, reward, or policy modules directly.

UNIT OF COMPARISON -- DISTINCT NEWLY OBSERVED FRAMES, NOT STEPS: only
transitions with ``transition_consumed=True`` are included. A ``safe_stop``
no-op step (``transition_consumed=False``) does not feed a new frame into
the pipeline -- its ``safety_status`` is re-derived from the SAME already-
processed outcome the preceding real step already scored, and its exposed
``sample_seq`` duplicates that preceding step's value (see
``edge.rl.environment``'s own INJECTION-LABEL RETENTION section and the
axis (ii) scoping review that preceded this increment). Axis (i) counts by
STEP because each step is a genuine, distinct policy decision even when
the underlying frame repeats; axis (ii) is not about policy decisions at
all -- it is about whether the tracker's state agrees with a given frame's
own injection ground truth, so counting the same frame twice (once for the
real step, again for a subsequent no-op safe_stop step referencing the
identical outcome) would double-count one observation as two. Restricting
to ``transition_consumed=True`` is the SMALLEST correct fix for this: it
excludes exactly the steps that observed no new frame, without requiring
an explicit ``sample_seq`` deduplication pass (deliberately deferred, not
implemented, in this first increment -- see the scoping review's own
open question on this point).

FOUR-WAY CLASSIFICATION per included observation:
  - agreement (active): an injection was active AND the tracker considered
    the system isolation-active.
  - agreement (nominal): no injection was active AND the tracker did NOT
    consider the system isolation-active.
  - tracker missed injection: an injection was active but the tracker did
    NOT flag isolation-active.
  - tracker flagged without injection: no injection was active but the
    tracker DID consider the system isolation-active (NOT necessarily a
    false positive in a strong sense -- a clean scenario's own organic
    wear-out degradation can independently push a channel's trust band
    down with no injection present at all; this axis validates against
    INJECTION ground truth specifically, not against "nothing anomalous is
    happening").

INJECTION ATTEMPTED VS. INJECTION DETECTABLE (must not be conflated):
``active_injection_labels`` records that an injection was ATTEMPTED at a
frame -- it says nothing about whether that injection was DETECTABLE by
this pipeline's own trust/anomaly logic. ``AdaptiveStealthFDI`` in
particular (see ``edge/injection/injections.py``'s own docstring) is
explicitly designed to keep its per-sample deviation under a naive
detection bound -- a "tracker missed injection" count for this (or any)
injection type is NOT evidence of a detector failure; it may reflect the
tracker behaving exactly as any reasonable detector would against a
deliberately-evasive or simply too-small input. This is why per-
injection-type breakdowns are reported SEPARATELY below and never pooled
into one aggregate "miss rate" -- pooling would hide exactly this
distinction.

PER-INJECTION-TYPE ATTRIBUTION: an observation whose
``active_injection_labels`` names more than one injection type (a
simultaneous multi-injection scenario -- none exists among the currently
committed scenarios, but the data model allows it) is attributed to EACH
of its active types. Consequently, the per-type observation counts below
CAN sum to more than ``total_observations`` when multiple injections are
simultaneously active; they are not a partition of the total the way the
four-way classification above is.

NO THRESHOLD, NO VERDICT, NO REAL-WORLD CLAIM: this module computes counts
and ratios only, always alongside their own counts (never a bare
percentage). It does not choose, suggest, or imply any acceptable
agreement rate; does not compare against real hardware or real-world
data; and does not claim validation, safety, or production readiness for
any scenario or result. U06 (``project-state/DECISIONS.md``) remains
fully open -- nothing here resolves or partially resolves it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from edge.eval.rl_baseline_eval import EpisodeRecord

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"


@dataclass(frozen=True)
class InjectionTypeBreakdown:
    """Agreement/disagreement counts scoped to observations where this
    specific injection type was among the active labels (see module
    docstring's PER-INJECTION-TYPE ATTRIBUTION section -- an observation
    with multiple simultaneous injection types contributes to more than
    one of these breakdowns). Every observation counted here had an
    injection active by definition, so only the two applicable outcomes
    (agreement-active / tracker-missed) are tracked -- "agreement-nominal"
    and "tracker-flagged-without-injection" cannot occur for an injected
    observation."""

    injection_type: str
    observation_count: int
    agreement_active_count: int
    tracker_missed_count: int
    agreement_rate: float | None  # None iff observation_count == 0


@dataclass(frozen=True)
class NoInjectionBreakdown:
    """Agreement/disagreement counts scoped to observations where NO
    injection was active. Distinct from ``InjectionTypeBreakdown`` --
    "agreement" here means the tracker also considered the system
    nominal, not isolation-active."""

    observation_count: int
    agreement_nominal_count: int
    tracker_flagged_without_injection_count: int
    agreement_rate: float | None  # None iff observation_count == 0


@dataclass(frozen=True)
class TrackerAgreementSummary:
    """Axis (ii) coarse, presence-only tracker-vs-injection agreement
    summary for one ``EpisodeRecord`` -- see module docstring. Every
    count/rate here is simulation-only and carries no acceptable-
    threshold, validation, safety, or production-readiness claim.

    ``total_observations`` is the count of transitions with
    ``transition_consumed=True`` -- see module docstring's UNIT OF
    COMPARISON section. ``agreement_rate`` is ``None`` iff
    ``total_observations == 0``.
    """

    scenario_name: str
    baseline_name: str
    total_observations: int

    agreement_active_count: int
    agreement_nominal_count: int
    tracker_missed_injection_count: int
    tracker_flagged_without_injection_count: int
    agreement_rate: float | None

    per_injection_type: dict[str, InjectionTypeBreakdown] = field(default_factory=dict)
    no_injection: NoInjectionBreakdown | None = None

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def summarize_tracker_agreement(record: EpisodeRecord) -> TrackerAgreementSummary:
    """Compute axis (ii)'s coarse, presence-only tracker-vs-injection
    agreement summary for one ``EpisodeRecord`` -- see module docstring.
    Pure: reads ``record``/``record.transitions`` only, never mutates
    either, and constructs no new environment/gate/reward/policy object.
    """
    observations = [t for t in record.transitions if t.transition_consumed]

    agreement_active = 0
    agreement_nominal = 0
    tracker_missed = 0
    tracker_flagged_without_injection = 0

    per_type_observations: Counter[str] = Counter()
    per_type_agreement: Counter[str] = Counter()
    per_type_missed: Counter[str] = Counter()

    no_injection_observations = 0
    no_injection_agreement = 0
    no_injection_flagged = 0

    for t in observations:
        injected = bool(t.active_injection_labels)
        tracker_active = t.safety_status == "isolation_active"

        if injected and tracker_active:
            agreement_active += 1
        elif injected and not tracker_active:
            tracker_missed += 1
        elif not injected and not tracker_active:
            agreement_nominal += 1
        else:  # not injected and tracker_active
            tracker_flagged_without_injection += 1

        if injected:
            for injection_type in t.active_injection_labels:
                per_type_observations[injection_type] += 1
                if tracker_active:
                    per_type_agreement[injection_type] += 1
                else:
                    per_type_missed[injection_type] += 1
        else:
            no_injection_observations += 1
            if tracker_active:
                no_injection_flagged += 1
            else:
                no_injection_agreement += 1

    total = len(observations)
    agreement_rate = (agreement_active + agreement_nominal) / total if total > 0 else None

    per_injection_type: dict[str, InjectionTypeBreakdown] = {}
    for injection_type in sorted(per_type_observations):
        obs_count = per_type_observations[injection_type]
        agree_count = per_type_agreement[injection_type]
        missed_count = per_type_missed[injection_type]
        per_injection_type[injection_type] = InjectionTypeBreakdown(
            injection_type=injection_type,
            observation_count=obs_count,
            agreement_active_count=agree_count,
            tracker_missed_count=missed_count,
            agreement_rate=(agree_count / obs_count if obs_count > 0 else None),
        )

    no_injection = NoInjectionBreakdown(
        observation_count=no_injection_observations,
        agreement_nominal_count=no_injection_agreement,
        tracker_flagged_without_injection_count=no_injection_flagged,
        agreement_rate=(
            no_injection_agreement / no_injection_observations
            if no_injection_observations > 0
            else None
        ),
    )

    return TrackerAgreementSummary(
        scenario_name=record.scenario_name,
        baseline_name=record.baseline_name,
        total_observations=total,
        agreement_active_count=agreement_active,
        agreement_nominal_count=agreement_nominal,
        tracker_missed_injection_count=tracker_missed,
        tracker_flagged_without_injection_count=tracker_flagged_without_injection,
        agreement_rate=agreement_rate,
        per_injection_type=per_injection_type,
        no_injection=no_injection,
    )
