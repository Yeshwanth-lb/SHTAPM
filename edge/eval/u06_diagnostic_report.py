"""U06 aggregate diagnostic report -- pure, additive, opt-in. Runs the
four existing, independently-committed U06 axis/comparison summaries
(axis (i): ``edge.eval.u06_rate_summary``; axis (ii): ``edge.eval.
u06_tracker_agreement``; axis (iii): ``edge.eval.
u06_ground_truth_rate_summary``; channel-matched agreement: ``edge.eval.
u06_channel_agreement``) across the complete evaluation-scenario taxonomy
for both existing deterministic baselines, and reports the results
scenario-by-scenario, baseline-by-baseline -- never pooled.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

SCOPE -- AGGREGATION AND REPORTING ONLY: this module defines no new U06
axis, comparison, definition, denominator, or metric. It calls exactly the
four already-committed, unmodified summary functions
(``summarize_episode_rates``, ``summarize_tracker_agreement``,
``summarize_ground_truth_rates``, ``summarize_channel_agreement``) on
``EpisodeRecord``s produced by the two already-committed, unmodified
baseline runners (``run_baseline_policy_episode``,
``run_pure_fallback_episode``) over the already-committed
evaluation-scenario taxonomy (``SCENARIO_CLEAN_DEGRADATION`` plus all
eight ``INJECTION_TYPE_SCENARIOS`` members). It never constructs an
environment, gate, reward, or policy object directly, and never imports
anything from the injection-framework package, ``edge.rl.reward``,
``edge.rl.fallback_gate``, ``edge.rl.policy``, or ``edge.eval.rl_training``.

CHANNEL-MATCHED AGREEMENT WIRING (U06 scoping, aggregation-only increment
-- the channel-matched comparison metric itself was already approved and
built separately in ``edge.eval.u06_channel_agreement``; this increment
only adds it alongside the three axes already assembled here, exactly as
axis (iii) was itself added to this same module when it existed):
``summarize_channel_agreement()`` is called unmodified on the same
``EpisodeRecord`` every other summary function already reads.
``ScenarioBaselineResult`` gains one new, defaulted-free field,
``channel_agreement_summary``. This wiring does not implement `sample_seq`
deduplication, DQN-policy evaluation, or confidence-interval reporting,
and does not modify ``edge.eval.u06_channel_agreement`` or any of its
already-approved match/mismatch/zero-opportunity rules.

CONFIDENCE-INTERVAL WIRING (U06 scoping, aggregation-only increment -- the
Wilson score interval methodology itself was already approved and built
separately in ``edge.eval.u06_confidence_intervals``; this increment only
calls its already-existing, unmodified per-axis wrapper functions on the
same four summaries this module already computes): for every result, all
six existing rate types (axis (i) false-isolation/missed-fault, axis (ii)
tracker-agreement, axis (iii) false-isolation/missed-fault, and
channel-matched agreement) each gain one new ``WilsonScoreInterval | None``
field, computed by calling ``axis_i_false_isolation_interval()``,
``axis_i_missed_fault_interval()``, ``axis_ii_tracker_agreement_interval()``,
``axis_iii_false_isolation_interval()``, ``axis_iii_missed_fault_interval()``,
and ``channel_agreement_interval()`` directly on the already-computed
summary objects -- never on a rounded rate, never across seeds. This
wiring introduces no new interval methodology, no cross-seed or pooled
interval, and does not modify ``edge.eval.u06_confidence_intervals`` or
any of its already-approved Wilson-formula/95%-confidence-level/
zero-denominator rules.

NEVER POOLED: every one of this module's 9 scenarios x 2 baselines = 18
``ScenarioBaselineResult``s is reported independently. No global,
cross-scenario, or cross-baseline rate, average, or aggregate statistic of
any kind is computed anywhere in this module -- doing so would directly
contradict the U06 Operational Definitions Proposal's own section E
("never pooled across scenarios") and section F ("Clean degradation vs.
injected current spike scenarios -- always reported as fully separate
rows, never merged"), both already committed to
``project-state/DECISIONS.md`` and unchanged by this module.

DIAGNOSTIC ONLY -- NO THRESHOLD, NO VERDICT, NO REAL-WORLD CLAIM: this
module produces no pass/fail judgment, no acceptable-rate determination,
and no accuracy, safety, effectiveness, validation, or production-
readiness claim of any kind, for any scenario, baseline, or axis. Every
number any of the three wrapped summary functions produces retains
whatever disclaimers that function's own module docstring already
attaches to it (see each module's own REQUIRED METHODOLOGICAL
DISCLAIMERS-equivalent section) -- this module adds no new interpretation,
only assembles them into one report. U06 (``project-state/DECISIONS.md``)
remains fully open -- nothing here resolves or partially resolves it.

NO EXTERNAL ERROR SURFACE: ``build_diagnostic_report()`` takes no
parameters and exercises only already-validated, already-committed
scenario/baseline/axis combinations -- there is no user input, no I/O, and
no network/hardware access for it to fail on. The taxonomy size is fixed
at import time (9 scenarios), so the report always contains exactly
9 * 2 = 18 results; it is never empty and never partial under normal
operation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from edge.eval.rl_baseline_eval import (
    INJECTION_TYPE_SCENARIOS,
    SCENARIO_CLEAN_DEGRADATION,
    EpisodeRecord,
    ScenarioConfig,
    run_baseline_policy_episode,
    run_pure_fallback_episode,
)
from edge.eval.u06_channel_agreement import (
    ChannelAgreementSummary,
    summarize_channel_agreement,
)
from edge.eval.u06_confidence_intervals import (
    WilsonScoreInterval,
    axis_i_false_isolation_interval,
    axis_i_missed_fault_interval,
    axis_ii_tracker_agreement_interval,
    axis_iii_false_isolation_interval,
    axis_iii_missed_fault_interval,
    channel_agreement_interval,
)
from edge.eval.u06_ground_truth_rate_summary import (
    GroundTruthRateSummary,
    summarize_ground_truth_rates,
)
from edge.eval.u06_rate_summary import EpisodeRateSummary, summarize_episode_rates
from edge.eval.u06_tracker_agreement import (
    TrackerAgreementSummary,
    summarize_tracker_agreement,
)

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"

# The complete evaluation-scenario taxonomy, unmodified, read directly from
# edge.eval.rl_baseline_eval -- one clean scenario plus one scenario per
# edge.injection.injections.InjectionType member (see that module's own
# INJECTION-TYPE SCENARIO TAXONOMY docstring section).
_EVALUATION_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_CLEAN_DEGRADATION,
    *INJECTION_TYPE_SCENARIOS,
)

_BASELINE_RUNNERS: tuple[Callable[[ScenarioConfig], EpisodeRecord], ...] = (
    run_baseline_policy_episode,
    run_pure_fallback_episode,
)


@dataclass(frozen=True)
class ScenarioBaselineResult:
    """One scenario/baseline pair's independent axis (i)/(ii)/(iii) and
    channel-matched agreement summaries, plus their within-episode Wilson
    score confidence intervals -- see module docstring's NEVER POOLED
    section. Never combined with any other result.

    Every ``*_interval`` field is ``None`` iff its own source rate's
    denominator is zero -- see ``edge.eval.u06_confidence_intervals``'s own
    zero-denominator convention, unchanged here."""

    scenario_name: str
    baseline_name: str
    episode_rate_summary: EpisodeRateSummary
    tracker_agreement_summary: TrackerAgreementSummary
    ground_truth_rate_summary: GroundTruthRateSummary
    channel_agreement_summary: ChannelAgreementSummary

    axis_i_false_isolation_interval: WilsonScoreInterval | None
    axis_i_missed_fault_interval: WilsonScoreInterval | None
    axis_ii_tracker_agreement_interval: WilsonScoreInterval | None
    axis_iii_false_isolation_interval: WilsonScoreInterval | None
    axis_iii_missed_fault_interval: WilsonScoreInterval | None
    channel_agreement_interval: WilsonScoreInterval | None

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


@dataclass(frozen=True)
class AggregateDiagnosticReport:
    """The complete, scenario-separated U06 diagnostic report -- see
    module docstring. ``results`` is a flat, ordered tuple of
    ``ScenarioBaselineResult``s, one per (scenario, baseline) pair; it is
    NOT a pooled or averaged summary -- no such summary exists anywhere in
    this module."""

    results: tuple[ScenarioBaselineResult, ...]

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def build_diagnostic_report() -> AggregateDiagnosticReport:
    """Run all four existing U06 axis/comparison summaries over every
    (scenario, baseline) pair in the complete evaluation-scenario
    taxonomy, for both existing deterministic baselines -- see module
    docstring. Pure: reads only already-committed scenario/baseline/
    summary functions, constructs no new environment/gate/reward/policy
    object, and mutates nothing. Takes no parameters; always returns
    exactly ``len(_EVALUATION_SCENARIOS) * len(_BASELINE_RUNNERS)`` results
    (see module docstring's NO EXTERNAL ERROR SURFACE section).
    """
    results: list[ScenarioBaselineResult] = []
    for scenario in _EVALUATION_SCENARIOS:
        for runner in _BASELINE_RUNNERS:
            record = runner(scenario)
            episode_rate_summary = summarize_episode_rates(record)
            tracker_agreement_summary = summarize_tracker_agreement(record)
            ground_truth_rate_summary = summarize_ground_truth_rates(record)
            channel_agreement_summary = summarize_channel_agreement(record)
            results.append(
                ScenarioBaselineResult(
                    scenario_name=record.scenario_name,
                    baseline_name=record.baseline_name,
                    episode_rate_summary=episode_rate_summary,
                    tracker_agreement_summary=tracker_agreement_summary,
                    ground_truth_rate_summary=ground_truth_rate_summary,
                    channel_agreement_summary=channel_agreement_summary,
                    axis_i_false_isolation_interval=axis_i_false_isolation_interval(
                        episode_rate_summary
                    ),
                    axis_i_missed_fault_interval=axis_i_missed_fault_interval(
                        episode_rate_summary
                    ),
                    axis_ii_tracker_agreement_interval=axis_ii_tracker_agreement_interval(
                        tracker_agreement_summary
                    ),
                    axis_iii_false_isolation_interval=axis_iii_false_isolation_interval(
                        ground_truth_rate_summary
                    ),
                    axis_iii_missed_fault_interval=axis_iii_missed_fault_interval(
                        ground_truth_rate_summary
                    ),
                    channel_agreement_interval=channel_agreement_interval(
                        channel_agreement_summary
                    ),
                )
            )
    return AggregateDiagnosticReport(results=tuple(results))


def main() -> None:
    """Diagnostic entry point: ``python -m edge.eval.u06_diagnostic_report``.
    Prints a concise, scenario-separated summary of all 18 (scenario,
    baseline) results. NOT a validation claim, NOT a pass/fail judgment --
    see module docstring."""
    print("=== U06 aggregate diagnostic report (simulation-only, all axes) ===")
    report = build_diagnostic_report()
    for result in report.results:
        rates = result.episode_rate_summary
        agreement = result.tracker_agreement_summary
        ground_truth = result.ground_truth_rate_summary
        channel_agreement = result.channel_agreement_summary
        print(f"[{result.scenario_name}] {result.baseline_name}:")
        print(
            f"  axis (i)   proxy false_isolation_rate={rates.false_isolation_rate} "
            f"missed_fault_rate={rates.missed_fault_rate}"
        )
        print(
            f"  axis (ii)  tracker agreement_rate={agreement.agreement_rate} "
            f"(observations={agreement.total_observations})"
        )
        print(
            f"  axis (iii) ground-truth false_isolation_rate="
            f"{ground_truth.false_isolation_rate} "
            f"missed_fault_rate={ground_truth.missed_fault_rate}"
        )
        print(
            f"  channel-agreement channel_match_rate="
            f"{channel_agreement.channel_match_rate} "
            f"(observations={channel_agreement.channel_match_observation_count})"
        )
        ci = result.channel_agreement_interval
        print(
            f"  channel-agreement 95% Wilson interval="
            f"{(ci.lower_bound, ci.upper_bound) if ci is not None else None}"
        )
    print(
        "NOTE: every number above is diagnostic, simulation-only, and scenario-"
        "specific (data_source=synthetic, execution_mode=simulation, "
        "model_status=diagnostic_unvalidated). No number here is pooled across "
        "scenarios, is a threshold, is a verdict, or is a real-world accuracy, "
        "safety, effectiveness, validation, or production-readiness claim. Every "
        "confidence interval printed above is a within-episode Wilson score "
        "interval only -- never a cross-seed or pooled uncertainty estimate."
    )


if __name__ == "__main__":
    main()
