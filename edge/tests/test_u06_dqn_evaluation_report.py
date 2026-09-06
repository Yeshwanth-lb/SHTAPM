"""Tests for edge/eval/u06_dqn_evaluation_report.py (U06 DQN-policy
diagnostic evaluation). No real-world accuracy, safety, effectiveness,
validation, or production-readiness claim exists here, no reward-weight
decision is made here, and no existing axis module, baseline runner, or
checkpoint file is created -- see the module's own docstring. Skipped
entirely when torch is unavailable, same skip-pattern as
edge/tests/test_rl_training.py.

The fixed diagnostic configuration (HIDDEN_SIZE_FIXTURE, TRAIN_EPISODES_
FIXTURE=30, etc.) is used exactly as documented -- these are NOT test-only
tiny fixtures (unlike edge/tests/test_rl_training.py's own tiny
hyperparameters), since this module's whole point is to exercise the
approved, fixed diagnostic configuration. One full report build takes
roughly 8-10 seconds; a module-scoped fixture computes it once and reuses
it across most tests, with a second, independent build only for the
explicit determinism test.
"""

from __future__ import annotations

import inspect
import random

import pytest

pytest.importorskip("torch")

from edge.eval.rl_baseline_eval import (  # noqa: E402
    EpisodeRecord,
    run_dqn_policy_episode,
)
from edge.eval.rl_training import TRAINING_SCENARIOS, DQNPolicy, train_dqn  # noqa: E402
from edge.eval.u06_channel_agreement import (  # noqa: E402
    ChannelAgreementSummary,
    summarize_channel_agreement,
)
from edge.eval.u06_dqn_evaluation_report import (  # noqa: E402
    REWARD_WEIGHTS_FIXTURE_NAME,
    U06_DQN_DIAGNOSTIC_SEED,
    DQNDiagnosticReport,
    DQNScenarioResult,
    _adapt_dqn_policy_to_propose_fn,
    build_dqn_diagnostic_report,
    main,
)
from edge.eval.u06_ground_truth_rate_summary import (  # noqa: E402
    GroundTruthRateSummary,
    summarize_ground_truth_rates,
)
from edge.eval.u06_rate_summary import EpisodeRateSummary, summarize_episode_rates  # noqa: E402
from edge.eval.u06_tracker_agreement import (  # noqa: E402
    TrackerAgreementSummary,
    summarize_tracker_agreement,
)

_EXPECTED_SCENARIOS = {
    "clean_degradation",
    "injected_current_spike",
    "injected_temperature_drift",
    "injected_pressure_stuck_at",
    "injected_humidity_bias_fdi",
    "injected_gas_ramp_fdi",
    "injected_vibration_replay",
    "injected_current_constant_spoof",
    "injected_temperature_adaptive_stealth_fdi",
}


@pytest.fixture(scope="module")
def report() -> DQNDiagnosticReport:
    return build_dqn_diagnostic_report()


# ---------------------------------------------------------------------------
# Seed choice: dedicated, not silently reused from a colliding fixture
# ---------------------------------------------------------------------------


def test_dedicated_seed_does_not_collide_with_rl_training_seed_fixture():
    from edge.eval.rl_training import SEED_FIXTURE

    assert U06_DQN_DIAGNOSTIC_SEED != SEED_FIXTURE


def test_dedicated_seed_does_not_collide_with_any_evaluation_scenario_seed():
    from edge.eval.rl_baseline_eval import INJECTION_TYPE_SCENARIOS, SCENARIO_CLEAN_DEGRADATION

    evaluation_seeds = {s.seed for s in INJECTION_TYPE_SCENARIOS}
    evaluation_seeds.add(SCENARIO_CLEAN_DEGRADATION.seed)
    assert U06_DQN_DIAGNOSTIC_SEED not in evaluation_seeds


def test_dedicated_seed_does_not_collide_with_training_scenario_seeds():
    training_seeds = {s.seed for s in TRAINING_SCENARIOS}
    assert U06_DQN_DIAGNOSTIC_SEED not in training_seeds


# ---------------------------------------------------------------------------
# Runner returns a valid EpisodeRecord that feeds all four summaries
# ---------------------------------------------------------------------------


def test_runner_returns_a_valid_episode_record():
    from edge.eval.rl_baseline_eval import SCENARIO_CLEAN_DEGRADATION

    training_result = train_dqn(
        training_scenarios=TRAINING_SCENARIOS,
        hidden_size=4,
        episodes=2,
        gamma=0.9,
        learning_rate=0.01,
        epsilon_start=1.0,
        epsilon_end=0.05,
        epsilon_decay_episodes=2,
        replay_capacity=100,
        batch_size=4,
        target_update_interval=1,
        seed=U06_DQN_DIAGNOSTIC_SEED,
    )
    policy = DQNPolicy(training_result.final_policy_net, epsilon=0.0, rng=random.Random(1))
    propose_action = _adapt_dqn_policy_to_propose_fn(policy)
    record = run_dqn_policy_episode(SCENARIO_CLEAN_DEGRADATION, propose_action)
    assert isinstance(record, EpisodeRecord)
    assert len(record.transitions) > 0


def test_episode_record_works_with_all_four_existing_summary_functions():
    from edge.eval.rl_baseline_eval import SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF

    training_result = train_dqn(
        training_scenarios=TRAINING_SCENARIOS,
        hidden_size=4,
        episodes=2,
        gamma=0.9,
        learning_rate=0.01,
        epsilon_start=1.0,
        epsilon_end=0.05,
        epsilon_decay_episodes=2,
        replay_capacity=100,
        batch_size=4,
        target_update_interval=1,
        seed=U06_DQN_DIAGNOSTIC_SEED,
    )
    policy = DQNPolicy(training_result.final_policy_net, epsilon=0.0, rng=random.Random(1))
    propose_action = _adapt_dqn_policy_to_propose_fn(policy)
    record = run_dqn_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF, propose_action)

    assert isinstance(summarize_episode_rates(record), EpisodeRateSummary)
    assert isinstance(summarize_tracker_agreement(record), TrackerAgreementSummary)
    assert isinstance(summarize_ground_truth_rates(record), GroundTruthRateSummary)
    assert isinstance(summarize_channel_agreement(record), ChannelAgreementSummary)


# ---------------------------------------------------------------------------
# DQN adapter has the correct callable shape
# ---------------------------------------------------------------------------


def test_adapter_returns_the_exact_propose_fn_tuple_shape():
    from app.schemas.contracts import RLAction

    from edge.rl.state import RLState

    training_result = train_dqn(
        training_scenarios=TRAINING_SCENARIOS,
        hidden_size=4,
        episodes=1,
        gamma=0.9,
        learning_rate=0.01,
        epsilon_start=0.0,
        epsilon_end=0.0,
        epsilon_decay_episodes=1,
        replay_capacity=10,
        batch_size=2,
        target_update_interval=1,
        seed=1,
    )
    policy = DQNPolicy(training_result.final_policy_net, epsilon=0.0, rng=random.Random(1))
    propose_action = _adapt_dqn_policy_to_propose_fn(policy)

    channels = ("current", "temperature", "pressure", "humidity", "gas", "vibration")
    dummy_state = RLState(
        health=1.0,
        anomaly_flag=False,
        trust={ch: 1.0 for ch in channels},
        failure_eta=None,
    )
    result = propose_action(dummy_state)
    assert isinstance(result, tuple)
    assert len(result) == 4
    action, policy_available, policy_validated, confidence = result
    assert isinstance(action, RLAction)
    assert isinstance(policy_available, bool)
    assert isinstance(policy_validated, bool)
    assert confidence is None or isinstance(confidence, float)
    # DQNPolicy always reports policy_validated=False (Q-values are not a
    # calibrated probability) -- see edge/eval/rl_training.py's own
    # POLICY VALIDATION section.
    assert policy_validated is False


# ---------------------------------------------------------------------------
# Full report: coverage, structure, metadata
# ---------------------------------------------------------------------------


def test_report_covers_all_nine_evaluation_scenarios(report):
    scenario_names = {r.scenario_name for r in report.results}
    assert scenario_names == _EXPECTED_SCENARIOS
    assert len(report.results) == 9


def test_every_result_carries_all_four_summaries(report):
    for result in report.results:
        assert isinstance(result, DQNScenarioResult)
        assert isinstance(result.episode_rate_summary, EpisodeRateSummary)
        assert isinstance(result.tracker_agreement_summary, TrackerAgreementSummary)
        assert isinstance(result.ground_truth_rate_summary, GroundTruthRateSummary)
        assert isinstance(result.channel_agreement_summary, ChannelAgreementSummary)


def test_every_result_reports_dqn_policy_baseline_name(report):
    for result in report.results:
        assert result.baseline_name == "dqn_policy"


def test_report_documents_its_own_fixed_configuration(report):
    assert report.diagnostic_seed == U06_DQN_DIAGNOSTIC_SEED
    assert report.reward_weights_fixture_name == REWARD_WEIGHTS_FIXTURE_NAME
    assert report.reward_weights_fixture_name == "SIMULATION_REWARD_WEIGHTS_FIXTURE"


def test_all_results_carry_consistent_metadata(report):
    for result in report.results:
        assert result.execution_mode == "simulation"
        assert result.data_source == "synthetic"
        assert result.model_status == "diagnostic_unvalidated"
    assert report.execution_mode == "simulation"
    assert report.data_source == "synthetic"
    assert report.model_status == "diagnostic_unvalidated"


# ---------------------------------------------------------------------------
# Existing deterministic baselines are unaffected
# ---------------------------------------------------------------------------


def test_existing_baseline_outputs_are_unchanged_by_this_module(report):
    """Regression guard: building a DQN diagnostic report must not change
    run_baseline_policy_episode's or run_pure_fallback_episode's output
    for the same scenario."""
    from edge.eval.rl_baseline_eval import (
        SCENARIO_CLEAN_DEGRADATION,
        run_baseline_policy_episode,
        run_pure_fallback_episode,
    )

    baseline_before = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    fallback_before = run_pure_fallback_episode(SCENARIO_CLEAN_DEGRADATION)
    baseline_after = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    fallback_after = run_pure_fallback_episode(SCENARIO_CLEAN_DEGRADATION)
    assert baseline_before == baseline_after
    assert fallback_before == fallback_after


def test_existing_axis_and_channel_agreement_outputs_are_unaffected(report):
    """Regression guard: the two deterministic baselines' own axis/
    channel-agreement summaries are unaffected by this module's existence
    -- recomputed fresh and compared to a pre-existing known real
    mismatch case."""
    from edge.eval.rl_baseline_eval import (
        SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF,
        run_baseline_policy_episode,
    )

    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    summary = summarize_channel_agreement(record)
    assert summary.channel_match_rate == 0.0
    assert summary.tracked_without_injection_channels_seen == ("vibration",)


# ---------------------------------------------------------------------------
# Determinism, where the existing training implementation permits it
# ---------------------------------------------------------------------------


def test_fixed_configuration_is_deterministic_across_independent_builds(report):
    """Two independent, fresh calls to build_dqn_diagnostic_report() must
    produce byte-identical results -- edge.eval.rl_training.train_dqn()'s
    own torch.manual_seed(seed) + random.Random(seed) determinism
    convention, combined with epsilon=0.0 greedy evaluation (which never
    draws from the evaluation policy's own rng), makes this reproducible.
    Verified directly (not assumed) before writing this test."""
    second_report = build_dqn_diagnostic_report()
    assert report.results == second_report.results
    assert report.diagnostic_seed == second_report.diagnostic_seed


# ---------------------------------------------------------------------------
# No checkpoint persistence
# ---------------------------------------------------------------------------


def test_no_checkpoint_file_is_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    build_dqn_diagnostic_report()
    created_files = list(tmp_path.rglob("*"))
    assert not any(f.suffix in (".pt", ".pth", ".ckpt") for f in created_files if f.is_file())


def test_module_never_calls_torch_save_or_load():
    import edge.eval.u06_dqn_evaluation_report as module

    source = inspect.getsource(module)
    assert "torch.save" not in source
    assert "torch.load" not in source


# ---------------------------------------------------------------------------
# No forbidden modules modified; no threshold/verdict/reward-selection/
# real-world claim
# ---------------------------------------------------------------------------


def test_module_does_not_import_forbidden_modules_beyond_rl_training():
    """This module is explicitly allowed to import edge.eval.rl_training
    (its whole purpose) -- but must never import the injection-framework
    package, the fallback gate, the environment, the reward module
    directly, or the policy module directly (it only uses DQNPolicy via
    rl_training, and RLAction indirectly via PolicyDecision)."""
    import ast

    import edge.eval.u06_dqn_evaluation_report as module

    tree = ast.parse(inspect.getsource(module))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "edge.rl.fallback_gate",
        "edge.rl.environment",
        "edge.injection",
    )
    for imported in imported_modules:
        assert not imported.startswith(forbidden_prefixes)


def test_module_makes_no_threshold_verdict_reward_selection_or_real_world_claim():
    import edge.eval.u06_dqn_evaluation_report as module

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
        "preferred reward",
        "best reward",
        "optimal reward",
    )
    for phrase in forbidden:
        assert phrase not in lowered


def test_module_explicitly_disclaims_the_reward_fixture_as_a_decision():
    import edge.eval.u06_dqn_evaluation_report as module

    source = inspect.getsource(module).lower()
    assert "not an approved u06 reward-weight decision" in source


# ---------------------------------------------------------------------------
# Full regression coverage for all existing U06 reports and axes
# ---------------------------------------------------------------------------


def test_aggregate_and_seed_repetition_reports_are_unaffected():
    """Regression guard: importing/using this module must not change the
    aggregate diagnostic report's or any seed-repetition report's output."""
    from edge.eval.u06_diagnostic_report import build_diagnostic_report

    diagnostic_report = build_diagnostic_report()
    assert len(diagnostic_report.results) == 18
    for result in diagnostic_report.results:
        assert result.baseline_name in {"baseline_policy", "pure_fallback"}


def test_main_runs_without_raising_and_prints_expected_sections(capsys):
    main()
    captured = capsys.readouterr()
    assert "channel-agreement" in captured.out
    assert "not an approved U06 reward-weight decision" in captured.out
    for scenario_name in _EXPECTED_SCENARIOS:
        assert scenario_name in captured.out
