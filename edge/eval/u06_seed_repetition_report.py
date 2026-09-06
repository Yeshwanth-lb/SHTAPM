"""U06 seed-repetition report -- pure, additive, opt-in. Runs the four
existing, independently-committed U06 axis summaries (axis (i):
``edge.eval.u06_rate_summary``; axis (ii): ``edge.eval.
u06_tracker_agreement``; axis (iii): ``edge.eval.
u06_ground_truth_rate_summary``; channel-agreement: ``edge.eval.
u06_channel_agreement``) across the five clean-degradation seed
variants in ``edge.eval.rl_baseline_eval.
CLEAN_DEGRADATION_SEED_REPETITION_SCENARIOS`` for both existing
deterministic baselines, reporting every (seed, baseline) result
independently -- establishing the FIRST complete 5-seed coverage pattern
for one scenario shape, per §4 of the "U06 -- RL REWARD SHAPING
SPECIFICATION PROPOSAL" section (proposed minimum: at least 5 distinct
seeds per scenario).

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

SCOPE -- ONE SCENARIO SHAPE, FIVE SEEDS, NO NEW METRIC: this module
defines no new U06 axis, comparison, definition, denominator, or metric.
It calls exactly the four already-committed, unmodified summary functions
on ``EpisodeRecord``s produced by the two already-committed, unmodified
baseline runners, over five already-committed ``ScenarioConfig``s that
share one shape (clean degradation, no injections) and differ only in
seed. It never constructs an environment, gate, reward, or policy object
directly, and never imports anything from the injection-framework
package, ``edge.rl.reward``, ``edge.rl.fallback_gate``, ``edge.rl.policy``,
``edge.rl.environment``, or ``edge.eval.rl_training``.

NEVER POOLED, NEVER SUMMARIZED ACROSS SEEDS: every one of this module's
5 seeds x 2 baselines = 10 ``SeedRepetitionResult``s is reported
independently. This module computes NO average, pooled rate, min, max,
range, variance, or any other variability statistic across seeds -- doing
so would itself be a new, not-yet-approved cross-seed metric. Per-seed,
per-baseline results are the base unit and the ONLY unit this module
produces, matching the U06 Operational Definitions Proposal's own section
E ("per-episode raw rates and opportunity counts are the base unit,
reported before any cross-seed summary").

PARTIAL COVERAGE, NOT COMPLETION, OF §4: this module establishes
the 5-seed pattern for exactly ONE scenario shape (clean degradation).
§4's proposed minimum applies to EVERY scenario in the taxonomy
(the 8 injection-type scenarios plus this one) -- broader 5-seed coverage
across the other 8 scenarios remains unfinished and is NOT implemented
here.

DIAGNOSTIC ONLY -- NO THRESHOLD, NO VERDICT, NO REAL-WORLD CLAIM: this
module produces no pass/fail judgment and no accuracy, safety,
effectiveness, validation, or production-readiness claim of any kind, for
any seed, baseline, or axis. Every number any of the four wrapped
summary functions produces retains whatever disclaimers that function's
own module docstring already attaches to it -- this module adds no new
interpretation, only assembles per-seed results into one flat report. U06
(``project-state/DECISIONS.md``) remains fully open -- nothing here
resolves or partially resolves it.

NO EXTERNAL ERROR SURFACE: ``build_seed_repetition_report()`` takes no
parameters and exercises only already-validated, already-committed
scenario/baseline/axis combinations -- there is no user input, no I/O, and
no network/hardware access for it to fail on. The scenario count is fixed
at import time (5 seeds), so the report always contains exactly
5 * 2 = 10 results; it is never empty and never partial under normal
operation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from edge.eval.rl_baseline_eval import (
    CLEAN_DEGRADATION_SEED_REPETITION_SCENARIOS,
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

_BASELINE_RUNNERS: tuple[Callable[[ScenarioConfig], EpisodeRecord], ...] = (
    run_baseline_policy_episode,
    run_pure_fallback_episode,
)


@dataclass(frozen=True)
class SeedRepetitionResult:
    """One (scenario, seed, baseline) triple's independent axis (i)/(ii)/
    (iii) summaries -- see module docstring's NEVER POOLED section. Never
    combined with any other result, and never used to compute a
    cross-seed statistic."""

    scenario_name: str
    seed: int
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
class SeedRepetitionReport:
    """The complete, per-seed-separated U06 seed-repetition report for the
    clean-degradation scenario shape -- see module docstring. ``results``
    is a flat, ordered tuple of ``SeedRepetitionResult``s, one per (seed,
    baseline) pair; it is NOT a pooled, averaged, or otherwise
    cross-seed-summarized report -- no such computation exists anywhere in
    this module."""

    results: tuple[SeedRepetitionResult, ...]

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def build_seed_repetition_report() -> SeedRepetitionReport:
    """Run all four existing U06 axis summaries over every (seed,
    baseline) pair across the five clean-degradation seed variants, for
    both existing deterministic baselines -- see module docstring. Pure:
    reads only already-committed scenario/baseline/summary functions,
    constructs no new environment/gate/reward/policy object, and mutates
    nothing. Takes no parameters; always returns exactly
    ``len(CLEAN_DEGRADATION_SEED_REPETITION_SCENARIOS) * len(
    _BASELINE_RUNNERS)`` results (see module docstring's NO EXTERNAL ERROR
    SURFACE section).
    """
    results: list[SeedRepetitionResult] = []
    for scenario in CLEAN_DEGRADATION_SEED_REPETITION_SCENARIOS:
        for runner in _BASELINE_RUNNERS:
            record = runner(scenario)
            episode_rate_summary = summarize_episode_rates(record)
            tracker_agreement_summary = summarize_tracker_agreement(record)
            ground_truth_rate_summary = summarize_ground_truth_rates(record)
            channel_agreement_summary = summarize_channel_agreement(record)
            results.append(
                SeedRepetitionResult(
                    scenario_name=record.scenario_name,
                    seed=scenario.seed,
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
    return SeedRepetitionReport(results=tuple(results))


def main() -> None:
    """Diagnostic entry point: ``python -m edge.eval.u06_seed_repetition_report``.
    Prints a concise, per-seed-separated summary of all 10 (seed, baseline)
    results for the clean-degradation scenario shape. NOT a validation
    claim, NOT a pass/fail judgment, and NOT a cross-seed summary -- see
    module docstring."""
    print("=== U06 seed-repetition report: clean_degradation, 5 seeds (simulation-only) ===")
    report = build_seed_repetition_report()
    for result in report.results:
        rates = result.episode_rate_summary
        agreement = result.tracker_agreement_summary
        ground_truth = result.ground_truth_rate_summary
        channel_agreement = result.channel_agreement_summary
        print(f"[seed={result.seed}] {result.baseline_name}:")
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
        "NOTE: every number above is diagnostic, simulation-only, and per-seed-"
        "specific (data_source=synthetic, execution_mode=simulation, "
        "model_status=diagnostic_unvalidated). No average, pooled rate, min/max, "
        "or variability statistic is computed across seeds. No number here is a "
        "threshold, is a verdict, or is a real-world accuracy, safety, "
        "effectiveness, validation, or production-readiness claim. This covers "
        "only the clean-degradation scenario shape -- broader 5-seed coverage "
        "across the other 8 scenarios remains unfinished."
    )


if __name__ == "__main__":
    main()
