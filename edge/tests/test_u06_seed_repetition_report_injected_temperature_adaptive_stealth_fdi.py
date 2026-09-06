"""Tests for
edge/eval/u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi.py
(U06 seed-repetition report, ninth and final scenario shape -- pure,
additive, opt-in). No new axis, metric, threshold, verdict, cross-seed
statistic, or real-world claim exists here -- see the module's own
docstring.
"""

from __future__ import annotations

import inspect

from edge.eval.rl_baseline_eval import (
    INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS,
    INJECTION_TYPE_SCENARIOS,
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI,
    EpisodeRecord,
)
from edge.eval.u06_channel_agreement import ChannelAgreementSummary
from edge.eval.u06_confidence_intervals import WilsonScoreInterval
from edge.eval.u06_ground_truth_rate_summary import GroundTruthRateSummary
from edge.eval.u06_rate_summary import EpisodeRateSummary
from edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi import (
    SeedRepetitionReport,
    SeedRepetitionResult,
    build_seed_repetition_report,
)
from edge.eval.u06_tracker_agreement import TrackerAgreementSummary
from edge.models.degradation_generator import SyntheticDegradationGenerator

_EXPECTED_BASELINES = {"baseline_policy", "pure_fallback"}


# ---------------------------------------------------------------------------
# Five distinct seeds, no collisions
# ---------------------------------------------------------------------------


def test_original_plus_four_variants_produce_five_total_seeds():
    assert len(INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS) == 5


def test_all_five_seeds_are_distinct_from_one_another():
    seeds = [
        s.seed for s in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS
    ]
    assert len(seeds) == len(set(seeds)) == 5


def test_seed_variants_do_not_collide_with_any_existing_scenario_or_training_seed():
    # edge.eval.rl_training.TRAINING_SCENARIOS' own seeds (2001, 2002) --
    # referenced directly, not imported, so this lightweight test file
    # does not pull in edge.eval.rl_training's hard torch dependency.
    training_seeds = {2001, 2002}
    # The other eight seed-repetition sets' own new seeds -- referenced by
    # value, not imported, to keep this test focused on this module's own
    # scenario family.
    clean_degradation_variant_seeds = {1346, 1347, 1348, 1349}
    injected_current_spike_variant_seeds = {1350, 1351, 1352, 1353}
    injected_temperature_drift_variant_seeds = {1354, 1355, 1356, 1357}
    injected_pressure_stuck_at_variant_seeds = {1358, 1359, 1360, 1361}
    injected_humidity_bias_fdi_variant_seeds = {1362, 1363, 1364, 1365}
    injected_gas_ramp_fdi_variant_seeds = {1366, 1367, 1368, 1369}
    injected_vibration_replay_variant_seeds = {1370, 1371, 1372, 1373}
    injected_current_constant_spoof_variant_seeds = {1374, 1375, 1376, 1377}

    variant_seeds = {
        s.seed
        for s in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS
        if s is not SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI
    }
    existing_evaluation_seeds = {s.seed for s in INJECTION_TYPE_SCENARIOS}
    existing_evaluation_seeds.add(SCENARIO_CLEAN_DEGRADATION.seed)

    assert variant_seeds.isdisjoint(existing_evaluation_seeds)
    assert variant_seeds.isdisjoint(training_seeds)
    assert variant_seeds.isdisjoint(clean_degradation_variant_seeds)
    assert variant_seeds.isdisjoint(injected_current_spike_variant_seeds)
    assert variant_seeds.isdisjoint(injected_temperature_drift_variant_seeds)
    assert variant_seeds.isdisjoint(injected_pressure_stuck_at_variant_seeds)
    assert variant_seeds.isdisjoint(injected_humidity_bias_fdi_variant_seeds)
    assert variant_seeds.isdisjoint(injected_gas_ramp_fdi_variant_seeds)
    assert variant_seeds.isdisjoint(injected_vibration_replay_variant_seeds)
    assert variant_seeds.isdisjoint(injected_current_constant_spoof_variant_seeds)


def test_seed_variants_reuse_the_exact_injected_temperature_adaptive_stealth_fdi_profile():
    """Only `seed` and `name` may differ from
    SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI -- length, health
    range, degradation rate, channel config, and the AdaptiveStealthFDI
    injection must be identical."""
    for variant in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS:
        assert variant.length == SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.length
        assert (
            variant.start_health
            == SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.start_health
        )
        assert (
            variant.end_health
            == SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.end_health
        )
        assert (
            variant.degradation_rate
            == SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.degradation_rate
        )
        assert (
            variant.channels == SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.channels
        )
        assert (
            variant.injections
            == SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.injections
        )


def test_adaptive_stealth_fdi_injection_parameters_are_preserved_exactly():
    for variant in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS:
        assert len(variant.injections) == 1
        injection = variant.injections[0]
        assert injection.channel == "temperature"
        assert injection.onset == 25
        assert injection.duration == 10
        assert injection.rate == 0.5
        assert injection.residual_cap == 2.0


def test_original_injected_temperature_adaptive_stealth_fdi_scenario_is_unchanged():
    """Regression guard: this increment must not alter
    SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI itself."""
    assert SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.seed == 1345
    assert (
        SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.name
        == "injected_temperature_adaptive_stealth_fdi"
    )
    assert (
        SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI
        in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS
    )


# ---------------------------------------------------------------------------
# Coverage: both baselines for every seed, exactly 10 results
# ---------------------------------------------------------------------------


def test_report_contains_exactly_ten_results():
    report = build_seed_repetition_report()
    assert isinstance(report, SeedRepetitionReport)
    assert len(report.results) == 10


def test_both_baselines_run_for_every_seed():
    report = build_seed_repetition_report()
    for scenario in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS:
        baselines_for_seed = {
            r.baseline_name for r in report.results if r.seed == scenario.seed
        }
        assert baselines_for_seed == _EXPECTED_BASELINES


def test_seed_baseline_pairs_are_all_unique():
    report = build_seed_repetition_report()
    pairs = [(r.seed, r.baseline_name) for r in report.results]
    assert len(pairs) == len(set(pairs)) == 10


def test_every_result_carries_all_four_summaries():
    report = build_seed_repetition_report()
    for result in report.results:
        assert isinstance(result, SeedRepetitionResult)
        assert isinstance(result.episode_rate_summary, EpisodeRateSummary)
        assert isinstance(result.tracker_agreement_summary, TrackerAgreementSummary)
        assert isinstance(result.ground_truth_rate_summary, GroundTruthRateSummary)
        assert isinstance(result.channel_agreement_summary, ChannelAgreementSummary)


# ---------------------------------------------------------------------------
# Scenario, seed, and baseline labels remain separate
# ---------------------------------------------------------------------------


def test_scenario_seed_and_baseline_labels_are_all_reported_and_consistent():
    report = build_seed_repetition_report()
    for result in report.results:
        assert result.scenario_name.startswith("injected_temperature_adaptive_stealth_fdi")
        assert isinstance(result.seed, int)
        assert result.episode_rate_summary.scenario_name == result.scenario_name
        assert result.tracker_agreement_summary.scenario_name == result.scenario_name
        assert result.ground_truth_rate_summary.scenario_name == result.scenario_name
        assert result.channel_agreement_summary.scenario_name == result.scenario_name


def test_each_seed_maps_to_its_own_distinct_scenario_name():
    report = build_seed_repetition_report()
    seed_to_names = {}
    for result in report.results:
        seed_to_names.setdefault(result.seed, set()).add(result.scenario_name)
    for names in seed_to_names.values():
        assert len(names) == 1  # one scenario name per seed, never conflated
    all_names = {name for names in seed_to_names.values() for name in names}
    assert len(all_names) == 5


# ---------------------------------------------------------------------------
def test_channel_agreement_wiring_introduces_no_per_channel_or_partial_match_field():
    """Structural guard: wiring channel-agreement into this report must not
    introduce a per-channel breakdown or partial-match category anywhere --
    ChannelAgreementSummary's own fields are unchanged by this increment."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ChannelAgreementSummary)}
    assert not any("per_channel" in name or "partial" in name for name in field_names)


def test_existing_axis_summaries_are_unchanged_by_channel_agreement_wiring():
    """Regression guard: adding channel_agreement_summary must not change
    any value the three pre-existing axis summaries report, for every
    seed/baseline pair -- each is independently recomputed fresh and
    compared against the report's own stored value."""
    from edge.eval.rl_baseline_eval import run_baseline_policy_episode, run_pure_fallback_episode
    from edge.eval.u06_ground_truth_rate_summary import summarize_ground_truth_rates
    from edge.eval.u06_rate_summary import summarize_episode_rates
    from edge.eval.u06_tracker_agreement import summarize_tracker_agreement

    runners = {
        "baseline_policy": run_baseline_policy_episode,
        "pure_fallback": run_pure_fallback_episode,
    }
    report = build_seed_repetition_report()
    for result in report.results:
        scenario = next(
            s
            for s in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS
            if s.seed == result.seed
        )
        record = runners[result.baseline_name](scenario)
        assert result.episode_rate_summary == summarize_episode_rates(record)
        assert result.tracker_agreement_summary == summarize_tracker_agreement(record)
        assert result.ground_truth_rate_summary == summarize_ground_truth_rates(record)



def test_zero_channel_match_opportunities_across_all_seeds_and_baselines():
    """Verified directly: this scenario shape never produces a
    channel-match opportunity for any of its 5 seeds under either
    baseline -- this report must preserve None, never 0.0."""
    report = build_seed_repetition_report()
    for result in report.results:
        summary = result.channel_agreement_summary
        assert summary.channel_match_observation_count == 0
        assert summary.channel_match_rate is None
        assert summary.channel_match_rate != 0.0


def test_every_result_carries_all_six_confidence_interval_fields():
    report = build_seed_repetition_report()
    for result in report.results:
        for interval in (
            result.axis_i_false_isolation_interval,
            result.axis_i_missed_fault_interval,
            result.axis_ii_tracker_agreement_interval,
            result.axis_iii_false_isolation_interval,
            result.axis_iii_missed_fault_interval,
            result.channel_agreement_interval,
        ):
            assert interval is None or isinstance(interval, WilsonScoreInterval)


def test_confidence_interval_wiring_introduces_no_pooled_field():
    """Structural guard: no field on SeedRepetitionResult or
    SeedRepetitionReport may suggest cross-seed pooling."""
    import dataclasses

    for cls in (SeedRepetitionResult, SeedRepetitionReport):
        field_names = {f.name for f in dataclasses.fields(cls)}
        assert not any(
            "pooled" in name or "mean" in name or "stdev" in name or "variance" in name
            for name in field_names
        )


def test_channel_agreement_interval_uses_original_counts():
    report = build_seed_repetition_report()
    for result in report.results:
        interval = result.channel_agreement_interval
        if interval is not None:
            summary = result.channel_agreement_summary
            assert interval.numerator == summary.channel_match_count
            assert interval.denominator == summary.channel_match_observation_count



def test_channel_agreement_interval_is_none_across_all_seeds_and_baselines():
    """Verified directly: this scenario shape never produces a channel-
    match opportunity for any of its 5 seeds under either baseline -- the
    interval field must be None for every result, matching
    channel_match_rate."""
    report = build_seed_repetition_report()
    for result in report.results:
        assert result.channel_agreement_summary.channel_match_rate is None
        assert result.channel_agreement_interval is None


# Never pooled: no cross-seed statistic exists
# ---------------------------------------------------------------------------


def test_report_has_no_pooled_or_cross_seed_statistic_field():
    """Structural guard: SeedRepetitionReport must carry only the flat
    per-(seed, baseline) results tuple plus metadata -- no field computing
    any cross-seed average, min, max, range, or variance."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(SeedRepetitionReport)}
    assert field_names == {"results", "execution_mode", "data_source", "model_status"}


def test_module_never_computes_a_rate_or_cross_seed_statistic_of_its_own():
    """AST-based check (not a source-text scan, so a comment or docstring
    mentioning division/averages cannot trigger a false pass or fail): the
    module must contain no arithmetic Div, and no builtin min/max/sum/
    statistics call, anywhere in its own code."""
    import ast

    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    tree = ast.parse(inspect.getsource(module))

    division_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    ]
    assert division_nodes == []

    forbidden_call_names = {"min", "max", "sum", "mean", "median", "stdev", "variance"}
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert call_names.isdisjoint(forbidden_call_names)


def test_results_for_different_seeds_are_independently_computed():
    """Each seed's episode is built via a fresh call to the existing
    baseline runner over its own ScenarioConfig -- proving independent
    computation (distinct result objects from distinct calls), not a
    shared/cached run reused across seeds. NOTE: for this scenario/episode
    length, this project's degradation generator produces byte-identical
    cumulative_reward/final_health across all 5 seeds (verified directly,
    and consistent with all eight prior seed-repetition sets showing the
    same behavior) -- so this test does not assert a value difference that
    does not actually occur; it verifies structural independence only."""
    report = build_seed_repetition_report()
    by_seed = {r.seed: r for r in report.results if r.baseline_name == "baseline_policy"}
    result_ids = {id(result) for result in by_seed.values()}
    assert len(result_ids) == len(by_seed) == 5


# ---------------------------------------------------------------------------
# No mutation of underlying data
# ---------------------------------------------------------------------------


def test_build_seed_repetition_report_does_not_mutate_anything_across_calls():
    first = build_seed_repetition_report()
    second = build_seed_repetition_report()

    first_by_key = {(r.seed, r.baseline_name): r for r in first.results}
    second_by_key = {(r.seed, r.baseline_name): r for r in second.results}
    assert first_by_key.keys() == second_by_key.keys()
    for key, first_result in first_by_key.items():
        second_result = second_by_key[key]
        assert (
            first_result.episode_rate_summary.false_isolation_rate
            == second_result.episode_rate_summary.false_isolation_rate
        )
        assert (
            first_result.tracker_agreement_summary.agreement_rate
            == second_result.tracker_agreement_summary.agreement_rate
        )


def test_build_seed_repetition_report_returns_new_episode_records_not_shared_state():
    report = build_seed_repetition_report()
    for result in report.results:
        assert not isinstance(result, EpisodeRecord)


def test_scenario_definitions_are_not_mutated_by_building_the_report():
    seeds_before = tuple(
        s.seed for s in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS
    )
    names_before = tuple(
        s.name for s in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS
    )

    build_seed_repetition_report()

    seeds_after = tuple(
        s.seed for s in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS
    )
    names_after = tuple(
        s.name for s in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS
    )
    assert seeds_before == seeds_after
    assert names_before == names_after


# ---------------------------------------------------------------------------
# Zero-result / error-handling: the report is never empty or partial
# ---------------------------------------------------------------------------


def test_report_is_never_empty_under_normal_operation():
    report = build_seed_repetition_report()
    assert len(report.results) > 0
    assert len(report.results) == 10


def test_build_seed_repetition_report_takes_no_parameters():
    signature = inspect.signature(build_seed_repetition_report)
    assert len(signature.parameters) == 0


# ---------------------------------------------------------------------------
# Structural: no threshold, verdict, real-world, or new-axis claim
# ---------------------------------------------------------------------------


def test_module_makes_no_threshold_verdict_or_real_world_claim():
    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    source = inspect.getsource(module)
    lowered = source.lower()
    forbidden = (
        "the acceptable rate is",
        "the acceptable threshold is",
        "is validated",
        "confirmed safe",
        "confirmed accurate",
        "proven safe",
        "proven accurate",
        "production-ready",
        "production ready",
        "pass\"",
        "fail\"",
        "passed the",
        "failed the",
    )
    for phrase in forbidden:
        assert phrase not in lowered


def test_module_does_not_import_forbidden_modules():
    """The module docstring legitimately NAMES these modules to state the
    scope boundary -- what must never exist is an actual import, checked
    via AST rather than a source-text scan."""
    import ast

    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    tree = ast.parse(inspect.getsource(module))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "edge.rl.reward",
        "edge.rl.fallback_gate",
        "edge.rl.policy",
        "edge.rl.environment",
        "edge.eval.rl_training",
        "edge.injection",
    )
    for imported in imported_modules:
        assert not imported.startswith(forbidden_prefixes)


def test_module_has_no_hardware_network_or_actuation_imports():
    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RelayController", "FakeActuator", "SelfHealOrchestrator", "paho"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


def test_module_does_not_modify_the_other_seed_repetition_modules():
    """This module must exist alongside the eight prior seed-repetition
    modules, never replacing or importing from them."""
    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    source = inspect.getsource(module)
    assert "from edge.eval.u06_seed_repetition_report import" not in source
    assert "from edge.eval.u06_seed_repetition_report_injected_current_spike import" not in source
    assert (
        "from edge.eval.u06_seed_repetition_report_injected_temperature_drift import"
        not in source
    )
    assert (
        "from edge.eval.u06_seed_repetition_report_injected_pressure_stuck_at import"
        not in source
    )
    assert (
        "from edge.eval.u06_seed_repetition_report_injected_humidity_bias_fdi import"
        not in source
    )
    assert (
        "from edge.eval.u06_seed_repetition_report_injected_gas_ramp_fdi import"
        not in source
    )
    assert (
        "from edge.eval.u06_seed_repetition_report_injected_vibration_replay import"
        not in source
    )
    assert (
        "from edge.eval.u06_seed_repetition_report_injected_current_constant_spoof import"
        not in source
    )


def test_module_documents_the_empirical_note_disclaimer():
    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    source = inspect.getsource(module).lower()
    assert "empirical note" in source
    assert "byte-identical" in source
    assert "not investigated" in source or "not investigated, explained" in source
    assert "proof that seed variation" in source
    assert "impossible" in source
    assert "pooled or shared" in source


def test_module_documents_the_adaptive_stealth_fdi_temperature_characteristic_as_scenario_only():
    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    source = inspect.getsource(module).lower()
    assert "adaptivestealthfdi-on-temperature characteristic" in source
    assert "any claim about how a real adaptive" in source
    assert "attack" in source and "would behave in practice" in source


def test_module_documents_the_ambient_and_ramp_then_plateau_values():
    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    source = inspect.getsource(module)
    assert "26.0" in source
    assert "+0.5, +1.0, +1.5, +2.0" in source


def test_module_documents_section_d_completion_across_all_nine_shapes():
    import edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi as module

    source = inspect.getsource(module).lower()
    assert "all 9 of 9" in source or "9 of 9 scenario shapes" in source
    assert "does not resolve u06" in source


# ---------------------------------------------------------------------------
# main() is a simple, working printer
# ---------------------------------------------------------------------------


def test_main_runs_without_raising_and_prints_all_seeds(capsys):
    from edge.eval.u06_seed_repetition_report_injected_temperature_adaptive_stealth_fdi import (
        main,
    )

    main()
    captured = capsys.readouterr()
    for scenario in INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI_SEED_REPETITION_SCENARIOS:
        assert str(scenario.seed) in captured.out
    assert "axis (i)" in captured.out
    assert "axis (ii)" in captured.out
    assert "axis (iii)" in captured.out
    assert "channel-agreement" in captured.out
    assert "channel_match_rate" in captured.out


# ---------------------------------------------------------------------------
# Empirical characteristic: ramp-then-plateau against a flat ambient baseline
# ---------------------------------------------------------------------------


def test_ambient_temperature_is_flat_and_injection_produces_the_ramp_then_plateau_offsets():
    """Directly builds the raw clean/injected temperature streams (bypassing
    the episode runner) to verify, frame-by-frame, the exact
    ramp-then-plateau shape documented in the module's own docstring:
    offsets +0.5, +1.0, +1.5, +2.0 for the first four active steps, then
    +2.0 (the capped bound) for the remaining six active steps -- and that
    the two streams are identical outside the [25, 35) injection window."""
    scenario = SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI
    generator = SyntheticDegradationGenerator(
        length=scenario.length,
        start_health=scenario.start_health,
        end_health=scenario.end_health,
        degradation_rate=scenario.degradation_rate,
        seed=scenario.seed,
        channels=scenario.channels,
    )
    timestamps = [f"2024-01-01T00:{i:02d}:00Z" for i in range(scenario.length)]
    trajectory = generator.generate(timestamps)
    clean_frames = trajectory.frames

    injection = scenario.injections[0]
    injected_frames = injection.apply(clean_frames).frames

    clean_temps = [f.sensors.temperature for f in clean_frames]
    injected_temps = [f.sensors.temperature for f in injected_frames]

    # Ambient (uninjected) temperature is flat at 26.0 everywhere.
    assert set(clean_temps) == {26.0}

    # Streams are identical outside the [25, 35) injection window.
    assert clean_temps[:25] == injected_temps[:25]
    assert clean_temps[35:] == injected_temps[35:]

    # Exact ramp-then-plateau offsets during the active window.
    offsets = [
        round(injected_temps[i] - clean_temps[i], 4) for i in range(25, 35)
    ]
    assert offsets == [0.5, 1.0, 1.5, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0]

    # Injected values themselves, against the flat 26.0 ambient baseline.
    assert injected_temps[25:35] == [
        26.5,
        27.0,
        27.5,
        28.0,
        28.0,
        28.0,
        28.0,
        28.0,
        28.0,
        28.0,
    ]
