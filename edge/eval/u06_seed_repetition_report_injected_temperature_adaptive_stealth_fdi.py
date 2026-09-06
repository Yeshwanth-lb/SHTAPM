"""U06 seed-repetition report -- injected_temperature_adaptive_stealth_fdi
scenario shape -- pure, additive, opt-in. Runs the three existing,
independently-committed U06 axis summaries (axis (i): ``edge.eval.
u06_rate_summary``; axis (ii): ``edge.eval.u06_tracker_agreement``; axis
(iii): ``edge.eval.u06_ground_truth_rate_summary``) across the five
injected_temperature_adaptive_stealth_fdi seed variants in ``edge.eval.
rl_baseline_eval.INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_
SCENARIOS`` for both existing deterministic baselines, reporting every
(seed, baseline) result independently -- this is the NINTH (and final)
scenario shape covered by the U06 seed-repetition pattern (after ``edge.
eval.u06_seed_repetition_report``'s own clean-degradation coverage, ``edge.
eval.u06_seed_repetition_report_injected_current_spike``'s own coverage,
``edge.eval.u06_seed_repetition_report_injected_temperature_drift``'s own
coverage, ``edge.eval.u06_seed_repetition_report_injected_pressure_
stuck_at``'s own coverage, ``edge.eval.
u06_seed_repetition_report_injected_humidity_bias_fdi``'s own coverage,
``edge.eval.u06_seed_repetition_report_injected_gas_ramp_fdi``'s own
coverage, ``edge.eval.u06_seed_repetition_report_injected_vibration_
replay``'s own coverage, and ``edge.eval.
u06_seed_repetition_report_injected_current_constant_spoof``'s own
coverage), per §4 of the "U06 -- RL REWARD SHAPING SPECIFICATION
PROPOSAL" section (proposed minimum: at least 5 distinct seeds per scenario).

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

SCOPE -- ONE SCENARIO SHAPE, FIVE SEEDS, NO NEW METRIC: this module
defines no new U06 axis, comparison, definition, denominator, or metric.
It calls exactly the three already-committed, unmodified summary functions
on ``EpisodeRecord``s produced by the two already-committed, unmodified
baseline runners, over five already-committed ``ScenarioConfig``s that
share one shape (a single, unchanged temperature-channel
``AdaptiveStealthFDI`` injection on the same clean-degradation-shaped
trajectory) and differ only in seed. It never constructs an environment,
gate, reward, or policy object directly, and never imports anything from
the injection-framework package, ``edge.rl.reward``, ``edge.rl.
fallback_gate``, ``edge.rl.policy``, ``edge.rl.environment``, or ``edge.
eval.rl_training``. It also does not modify any of the eight existing
seed-repetition modules (clean degradation, injected_current_spike,
injected_temperature_drift, injected_pressure_stuck_at, injected_humidity_
bias_fdi, injected_gas_ramp_fdi, injected_vibration_replay, injected_
current_constant_spoof) -- all nine modules exist side by side,
structurally identical in shape, each scoped to its own scenario.

NEVER POOLED, NEVER SUMMARIZED ACROSS SEEDS: every one of this module's
5 seeds x 2 baselines = 10 ``SeedRepetitionResult``s is reported
independently. This module computes NO average, pooled rate, min, max,
range, variance, or any other variability statistic across seeds -- doing
so would itself be a new, not-yet-approved cross-seed metric. Per-seed,
per-baseline results are the base unit and the ONLY unit this module
produces, matching the U06 Operational Definitions Proposal's own section
E ("per-episode raw rates and opportunity counts are the base unit,
reported before any cross-seed summary").

§4 COVERAGE NOW COMPLETE ACROSS ALL NINE SCENARIO SHAPES: with
this module, all 9 of 9 evaluation-scenario shapes (clean degradation,
injected_current_spike, injected_temperature_drift, injected_pressure_
stuck_at, injected_humidity_bias_fdi, injected_gas_ramp_fdi, injected_
vibration_replay, injected_current_constant_spoof, injected_temperature_
adaptive_stealth_fdi) now have 5-seed coverage, satisfying §4's
proposed minimum for every scenario in the taxonomy. This completion is
STRICTLY SCOPED to the proposed 5-distinct-seeds-per-scenario minimum --
it does NOT resolve U06, does NOT establish channel-matched comparison or
DQN-policy evaluation, and does NOT constitute human sign-off accepting
the Operational Definitions Proposal itself. U06 remains fully open.

ADAPTIVESTEALTHFDI-ON-TEMPERATURE CHARACTERISTIC (a property of the
already-committed synthetic scenario, restated here for accuracy, NOT a
real-world conclusion): ``temperature`` is NOT one of the channels
configured in ``edge.eval.rl_baseline_eval._EVALUATION_DEGRADATION_
PROFILE`` (only ``vibration`` is), so the degradation generator returns a
flat, unconfigured baseline constant for ``temperature`` on every frame
regardless of index or seed (see ``edge/models/degradation_generator.
py``'s own ``_channel_sample()`` "unconfigured" branch) -- verified
directly: the ambient (uninjected) ``temperature`` stream is constant at
every frame (``26.0``). ``AdaptiveStealthFDI(channel="temperature",
onset=25, duration=10, rate=0.5, residual_cap=2.0)`` adds a per-sample
offset that grows at ``rate`` per active step but is capped at
``residual_cap`` (see ``edge/injection/injections.py``'s own
``AdaptiveStealthFDI._value()``) -- this is a FIFTH distinct mechanism
among the seed-repetition scenarios so far, different from ``StuckAt``
(freezes at the existing value), ``BiasFDI``/``RampFDI`` (fixed or
unbounded-growing additive offset), and ``ConstantSpoof`` (pins to an
absolute value): ``AdaptiveStealthFDI`` ramps its own additive offset only
until it hits a fixed bound, then holds flat at that bound for the rest of
the window. Verified directly, frame-by-frame, for the active window
``[25, 35)``: the offset is ``+0.5, +1.0, +1.5, +2.0`` for the first four
active steps, then holds at the capped ``+2.0`` for the remaining six
active steps (steps 5 through 10) -- i.e. the injected ``temperature``
stream is ``26.5, 27.0, 27.5, 28.0, 28.0, 28.0, 28.0, 28.0, 28.0, 28.0``
against the flat ``26.0`` ambient baseline, and the two streams are
identical outside ``[25, 35)``. This ramp-then-plateau shape is stated as
a characteristic of this synthetic scenario's own configuration -- not as
any claim about how a real adaptive or stealth false-data-injection attack
would behave in practice, and not as evidence for or against this
pipeline's real-world fault-detection or attack-detection capability.

EMPIRICAL NOTE (diagnostic observation, not investigated or resolved by
this increment): all 5 ``injected_temperature_adaptive_stealth_fdi``
seeds currently produce byte-identical ``cumulative_reward``,
``final_health``, and axis-summary values for this scenario and episode
length -- the same behavior already observed for the clean-degradation,
injected_current_spike, injected_temperature_drift, injected_pressure_
stuck_at, injected_humidity_bias_fdi, injected_gas_ramp_fdi, injected_
vibration_replay, and injected_current_constant_spoof seed sets (now the
NINTH and final scenario shape to show the identical pattern). As with
those prior increments, this is reported here as a diagnostic observation
about the current degradation-generator/scenario scale, for transparency
only -- it is NOT investigated, explained, or resolved by this increment,
and it must NOT be interpreted as proof that seed variation is
impossible, that these executions were pooled or shared, or that the
policy is accurate or safe. (Separately, the ADAPTIVESTEALTHFDI-ON-
TEMPERATURE CHARACTERISTIC above documents that this particular
scenario's injection IS observable against its own ambient baseline --
this does not explain the byte-identical-across-seeds pattern itself,
which remains unrelated to whether an individual injection's effect is
observable and is still not investigated by this increment.)

DIAGNOSTIC ONLY -- NO THRESHOLD, NO VERDICT, NO REAL-WORLD CLAIM: this
module produces no pass/fail judgment and no accuracy, safety,
effectiveness, validation, or production-readiness claim of any kind, for
any seed, baseline, or axis. Every number any of the three wrapped
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
    INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS,
    EpisodeRecord,
    ScenarioConfig,
    run_baseline_policy_episode,
    run_pure_fallback_episode,
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

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


@dataclass(frozen=True)
class SeedRepetitionReport:
    """The complete, per-seed-separated U06 seed-repetition report for the
    injected_temperature_adaptive_stealth_fdi scenario shape -- see module
    docstring. ``results`` is a flat, ordered tuple of
    ``SeedRepetitionResult``s, one per (seed, baseline) pair; it is NOT a
    pooled, averaged, or otherwise cross-seed-summarized report -- no such
    computation exists anywhere in this module."""

    results: tuple[SeedRepetitionResult, ...]

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def build_seed_repetition_report() -> SeedRepetitionReport:
    """Run all three existing U06 axis summaries over every (seed,
    baseline) pair across the five injected_temperature_adaptive_stealth_
    fdi seed variants, for both existing deterministic baselines -- see
    module docstring. Pure: reads only already-committed scenario/
    baseline/summary functions, constructs no new environment/gate/
    reward/policy object, and mutates nothing. Takes no parameters;
    always returns exactly ``len(INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_
    FDI_SEED_REPETITION_SCENARIOS) * len(_BASELINE_RUNNERS)`` results (see
    module docstring's NO EXTERNAL ERROR SURFACE section).
    """
    results: list[SeedRepetitionResult] = []
    for scenario in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS:
        for runner in _BASELINE_RUNNERS:
            record = runner(scenario)
            results.append(
                SeedRepetitionResult(
                    scenario_name=record.scenario_name,
                    seed=scenario.seed,
                    baseline_name=record.baseline_name,
                    episode_rate_summary=summarize_episode_rates(record),
                    tracker_agreement_summary=summarize_tracker_agreement(record),
                    ground_truth_rate_summary=summarize_ground_truth_rates(record),
                )
            )
    return SeedRepetitionReport(results=tuple(results))


def main() -> None:
    """Diagnostic entry point:
    ``python -m edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi``.
    Prints a concise, per-seed-separated summary of all 10 (seed,
    baseline) results for the injected_temperature_adaptive_stealth_fdi
    scenario shape. NOT a validation claim, NOT a pass/fail judgment, and
    NOT a cross-seed summary -- see module docstring."""
    print(
        "=== U06 seed-repetition report: injected_temperature_adaptive_stealth_fdi, "
        "5 seeds (simulation-only) ==="
    )
    report = build_seed_repetition_report()
    for result in report.results:
        rates = result.episode_rate_summary
        agreement = result.tracker_agreement_summary
        ground_truth = result.ground_truth_rate_summary
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
        "NOTE: every number above is diagnostic, simulation-only, and per-seed-"
        "specific (data_source=synthetic, execution_mode=simulation, "
        "model_status=diagnostic_unvalidated). No average, pooled rate, min/max, "
        "or variability statistic is computed across seeds. No number here is a "
        "threshold, is a verdict, or is a real-world accuracy, safety, "
        "effectiveness, validation, or production-readiness claim. This covers "
        "only the injected_temperature_adaptive_stealth_fdi scenario shape -- this "
        "completes the proposed 5-seed coverage across all 9 of 9 synthetic "
        "scenario shapes, but does not resolve U06 or establish policy accuracy, "
        "safety, effectiveness, real-world validation, or production readiness."
    )


if __name__ == "__main__":
    main()
