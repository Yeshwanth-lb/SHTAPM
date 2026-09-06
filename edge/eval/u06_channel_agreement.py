"""Channel-matched U06 tracker-vs-injection agreement -- pure, additive,
opt-in. See ``project-state/DECISIONS.md``'s "U06 -- Operational
Definitions Proposal Sign-Off" (DECISION RECORD) for the human-approved
design this module implements EXACTLY, and its "U06 -- RL REWARD SHAPING
SPECIFICATION PROPOSAL" for U06's own still-fully-open status.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

SCOPE -- CHANNEL-MATCHED, AXIS-(ii)-ADJACENT, ISOLATED MODULE: this module
compares the SPECIFIC injected channel(s) (``TransitionRecord.
active_injection_channels``) against the SPECIFIC tracked channel(s)
(``TransitionRecord.tracked_channels``) -- the exact comparison
``edge.eval.u06_tracker_agreement``'s own docstring has, since its first
version, explicitly named as unimplemented. This module does NOT modify
``u06_tracker_agreement.py`` or any of its output (``TrackerAgreementSummary``,
``agreement_rate``, ``total_observations`` are all untouched and unimported
here) -- it is a new, isolated, sibling module, exactly as every prior axis
(i)/(ii)/(iii) was added as its own file rather than an edit to a prior one.
It does NOT implement axis (i) (``edge.eval.u06_rate_summary``) or axis
(iii) (``edge.eval.u06_ground_truth_rate_summary``), does NOT implement
``sample_seq`` deduplication, and never imports anything from the
injection-framework package, ``edge.rl.reward``, ``edge.rl.fallback_gate``,
``edge.rl.policy``, ``edge.rl.environment``, or ``edge.eval.rl_training``.

DESIGN -- HUMAN-APPROVED, NOT THIS MODULE'S OWN CHOICE: every rule below was
explicitly approved by the U06 decision owner as a design decision separate
from, and subsequent to, the Operational Definitions Proposal sign-off
recorded in ``DECISIONS.md``. This module implements those rules verbatim;
it does not introduce, relax, or reinterpret any of them.

OBSERVATION UNIT -- DISTINCT NEWLY OBSERVED FRAMES, NOT STEPS: only
transitions with ``transition_consumed=True`` are included, for exactly the
same reason ``edge.eval.u06_tracker_agreement`` restricts itself the same
way: ``active_injection_channels`` and ``tracked_channels`` are both
frame-level ground-truth/tracker-state facts, not per-step policy
decisions, so a ``transition_consumed=False`` no-op step (re-deriving
state from an already-scored frame) must not be counted as a second,
independent observation of the same frame.

COMPARISON RULE -- EXACT SET EQUALITY, NO PARTIAL CREDIT: for each included
observation, let ``injected = frozenset(active_injection_channels)`` and
``tracked = frozenset(tracked_channels)``.
  - If BOTH are non-empty: this is a channel-match OPPORTUNITY.
    ``injected == tracked`` -> MATCH. Any difference at all (a missing
    channel, an extra channel, or both) -> MISMATCH. There is no
    partial-match category and no per-channel breakdown -- a scenario
    injecting two channels while the tracker holds only one, or holds one
    extra, is a single MISMATCH for that observation, never a fractional
    or per-channel-attributed result. This is a deliberate, human-approved
    choice, not an oversight -- see the design record above.
  - If ``injected`` is empty and ``tracked`` is non-empty: NOT a
    channel-match opportunity (nothing was injected to compare a tracked
    channel against). Reported separately, purely DESCRIPTIVELY (which
    channels were tracked), with NO verdict, rate, or judgment attached --
    axis (ii) already covers "tracker flagged without injection" as its
    own presence-only classification; this module adds no interpretation
    of it, only the channel identity for transparency.
  - If ``injected`` is non-empty and ``tracked`` is empty: NOT a
    channel-match opportunity -- this is axis (ii)'s existing "tracker
    missed injection" case in full; this module says nothing further about
    it (there is no tracked channel to compare against).
  - If both are empty: NOT a channel-match opportunity, and not reported
    anywhere -- there is nothing to describe or compare.

ZERO-OPPORTUNITY HANDLING: if an episode produces zero channel-match
opportunities (the ``injected AND tracked`` case never occurs),
``channel_match_rate`` is ``None`` -- NEVER ``0.0`` -- matching the
already-signed-off opportunity-denominator convention (``DECISIONS.md``'s
"U06 -- Operational Definitions Proposal Sign-Off", Decision 2).

NEVER POOLED ACROSS SEEDS OR SCENARIOS: this module returns one
``ChannelAgreementSummary`` per ``EpisodeRecord``, exactly as every other
axis summary does. No cross-seed, cross-scenario, or cross-baseline
average, pooled rate, or aggregate statistic of any kind is computed here
-- per the already-signed-off reporting convention (Decision 3 of the same
sign-off record), every (scenario, seed, baseline) result remains fully
independent.

NO THRESHOLD, NO VERDICT, NO REAL-WORLD CLAIM: this module computes counts
and a single ratio only. It does not choose, suggest, or imply any
acceptable match rate; does not compare against real hardware or
real-world data; and does not claim validation, safety, or production
readiness for any scenario or result. U06 (``project-state/DECISIONS.md``)
remains fully open -- nothing here resolves or partially resolves it, and
this module does not implement channel-matching for any purpose beyond the
diagnostic count/rate described above (no DQN evaluation, no reward
weight, no confidence interval, no ``sample_seq`` deduplication).
"""

from __future__ import annotations

from dataclasses import dataclass

from edge.eval.rl_baseline_eval import EpisodeRecord

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"


@dataclass(frozen=True)
class ChannelAgreementSummary:
    """Channel-matched agreement summary for one ``EpisodeRecord`` -- see
    module docstring. Every count/rate here is simulation-only and carries
    no acceptable-threshold, validation, safety, or production-readiness
    claim.

    ``channel_match_rate`` is ``None`` iff
    ``channel_match_observation_count == 0`` (see module docstring's
    ZERO-OPPORTUNITY HANDLING section) -- never ``0.0``.

    ``tracked_without_injection_channels_seen`` is purely descriptive (see
    module docstring's COMPARISON RULE section) -- it carries no match/
    mismatch verdict of its own.
    """

    scenario_name: str
    baseline_name: str

    channel_match_observation_count: int
    channel_match_count: int
    channel_mismatch_count: int
    channel_match_rate: float | None

    tracked_without_injection_observation_count: int
    tracked_without_injection_channels_seen: tuple[str, ...]

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def summarize_channel_agreement(record: EpisodeRecord) -> ChannelAgreementSummary:
    """Compute the channel-matched agreement summary for one
    ``EpisodeRecord`` -- see module docstring's COMPARISON RULE and
    OBSERVATION UNIT sections. Pure: reads ``record``/``record.transitions``
    only, never mutates either, and constructs no new environment/gate/
    reward/policy object.
    """
    channel_match_observation_count = 0
    channel_match_count = 0
    channel_mismatch_count = 0

    tracked_without_injection_observation_count = 0
    tracked_without_injection_channels_seen: set[str] = set()

    for t in record.transitions:
        if not t.transition_consumed:
            continue

        injected = frozenset(t.active_injection_channels)
        tracked = frozenset(t.tracked_channels)

        if injected and tracked:
            channel_match_observation_count += 1
            if injected == tracked:
                channel_match_count += 1
            else:
                channel_mismatch_count += 1
        elif tracked and not injected:
            tracked_without_injection_observation_count += 1
            tracked_without_injection_channels_seen |= tracked
        # else: injected and not tracked (axis (ii)'s own missed-injection
        # case), or neither -- not a channel-match opportunity, not
        # reported by this module at all.

    channel_match_rate = (
        channel_match_count / channel_match_observation_count
        if channel_match_observation_count > 0
        else None
    )

    return ChannelAgreementSummary(
        scenario_name=record.scenario_name,
        baseline_name=record.baseline_name,
        channel_match_observation_count=channel_match_observation_count,
        channel_match_count=channel_match_count,
        channel_mismatch_count=channel_mismatch_count,
        channel_match_rate=channel_match_rate,
        tracked_without_injection_observation_count=(
            tracked_without_injection_observation_count
        ),
        tracked_without_injection_channels_seen=tuple(
            sorted(tracked_without_injection_channels_seen)
        ),
    )


def main() -> None:
    """Diagnostic entry point:
    ``python -m edge.eval.u06_channel_agreement``. Prints a concise
    channel-match summary for the default two-scenario baseline set. NOT a
    validation claim, NOT a pass/fail judgment -- see module docstring."""
    from edge.eval.rl_baseline_eval import (
        SCENARIO_CLEAN_DEGRADATION,
        SCENARIO_INJECTED_CURRENT_SPIKE,
        run_baseline_policy_episode,
        run_pure_fallback_episode,
    )

    print("=== U06 channel-matched agreement (simulation-only) ===")
    for scenario in (SCENARIO_CLEAN_DEGRADATION, SCENARIO_INJECTED_CURRENT_SPIKE):
        for runner in (run_baseline_policy_episode, run_pure_fallback_episode):
            record = runner(scenario)
            summary = summarize_channel_agreement(record)
            print(f"[{summary.scenario_name}] {summary.baseline_name}:")
            print(
                f"  channel_match_rate={summary.channel_match_rate} "
                f"(match={summary.channel_match_count} "
                f"mismatch={summary.channel_mismatch_count} "
                f"observations={summary.channel_match_observation_count})"
            )
            print(
                f"  tracked_without_injection_observations="
                f"{summary.tracked_without_injection_observation_count} "
                f"channels_seen={summary.tracked_without_injection_channels_seen}"
            )
    print(
        "NOTE: every number above is diagnostic, simulation-only, and "
        "episode-specific (data_source=synthetic, execution_mode=simulation, "
        "model_status=diagnostic_unvalidated). No number here is pooled "
        "across scenarios or seeds, is a threshold, is a verdict, or is a "
        "real-world accuracy, safety, effectiveness, validation, or "
        "production-readiness claim."
    )


if __name__ == "__main__":
    main()
