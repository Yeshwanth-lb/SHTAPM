"""Tests for edge/eval/rl_training.py (diagnostic-only DQN training
harness). No real-world accuracy, safety, or validation claim exists here
-- see the module's own docstring. Skipped entirely when torch is
unavailable, same skip-pattern as edge/tests/test_prognosis_runtime.py.

Tiny hyperparameters throughout (hidden_size=4, episodes<=3, short
scenarios) -- these are TEST FIXTURES ONLY, distinct from the module's own
``*_FIXTURE`` diagnostic-run constants, chosen purely to keep test runtime
short.
"""

from __future__ import annotations

import random

import pytest

pytest.importorskip("torch")

from app.schemas.contracts import CHANNELS, RLAction  # noqa: E402

from edge.eval.rl_baseline_eval import (  # noqa: E402
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_CURRENT_SPIKE,
)
from edge.eval.rl_training import (  # noqa: E402
    ACTION_ORDER,
    DQN_POLICY_NAME,
    DQN_POLICY_VERSION,
    EVALUATION_SCENARIOS,
    EXECUTION_MODE,
    TRAINING_SCENARIOS,
    DQNPolicy,
    TrainingEpisodeRecord,
    TrainingRunResult,
    _DQNNet,
    evaluate_greedy,
    train_dqn,
)
from edge.rl.policy import Policy, PolicyDecision  # noqa: E402
from edge.rl.state import STATE_WIDTH, RLState  # noqa: E402


def _tiny_train(**overrides) -> TrainingRunResult:
    kwargs = {
        "training_scenarios": TRAINING_SCENARIOS[:1],
        "hidden_size": 4,
        "episodes": 3,
        "gamma": 0.9,
        "learning_rate": 0.01,
        "epsilon_start": 1.0,
        "epsilon_end": 0.5,
        "epsilon_decay_episodes": 3,
        "replay_capacity": 50,
        "batch_size": 4,
        "target_update_interval": 1,
        "seed": 7,
    }
    kwargs.update(overrides)
    return train_dqn(**kwargs)


# ---------------------------------------------------------------------------
# ACTION_ORDER / algorithm-shape basics
# ---------------------------------------------------------------------------


def test_action_order_covers_every_rlaction_exactly_once():
    assert set(ACTION_ORDER) == set(RLAction)
    assert len(ACTION_ORDER) == len(RLAction) == 5


def test_dqn_net_output_width_matches_action_order():
    import torch

    net = _DQNNet(hidden_size=4)
    output = net(torch.zeros(1, STATE_WIDTH))
    assert output.shape == (1, len(ACTION_ORDER))


# ---------------------------------------------------------------------------
# DQNPolicy: Protocol conformance and honest metadata
# ---------------------------------------------------------------------------


def test_dqn_policy_satisfies_the_policy_protocol():
    net = _DQNNet(hidden_size=4)
    policy = DQNPolicy(net, epsilon=0.0, rng=random.Random(0))
    assert isinstance(policy, Policy)


def test_dqn_policy_none_state_produces_safe_stop():
    net = _DQNNet(hidden_size=4)
    policy = DQNPolicy(net, epsilon=0.0, rng=random.Random(0))
    decision = policy.propose(None)
    assert decision.proposed_action == RLAction.safe_stop
    assert isinstance(decision, PolicyDecision)


def test_dqn_policy_always_reports_unvalidated_and_no_confidence():
    net = _DQNNet(hidden_size=4)
    trust = {ch: 0.9 for ch in CHANNELS}
    state = RLState(health=0.8, anomaly_flag=False, trust=trust, failure_eta=None)
    for epsilon in (0.0, 1.0):
        policy = DQNPolicy(net, epsilon=epsilon, rng=random.Random(0))
        decision = policy.propose(state)
        assert decision.policy_available is True
        assert decision.policy_validated is False
        assert decision.confidence is None
        assert decision.policy_name == DQN_POLICY_NAME
        assert decision.policy_version == DQN_POLICY_VERSION


def test_dqn_policy_version_is_explicitly_marked_unvalidated():
    assert "unvalidated" in DQN_POLICY_VERSION


def test_epsilon_zero_is_deterministic_greedy():
    net = _DQNNet(hidden_size=4)
    trust = {ch: 0.9 for ch in CHANNELS}
    state = RLState(health=0.8, anomaly_flag=False, trust=trust, failure_eta=None)
    policy_a = DQNPolicy(net, epsilon=0.0, rng=random.Random(1))
    policy_b = DQNPolicy(net, epsilon=0.0, rng=random.Random(2))
    assert policy_a.propose(state).proposed_action == policy_b.propose(state).proposed_action


def test_epsilon_one_always_explores():
    net = _DQNNet(hidden_size=4)
    trust = {ch: 0.9 for ch in CHANNELS}
    state = RLState(health=0.8, anomaly_flag=False, trust=trust, failure_eta=None)
    policy = DQNPolicy(net, epsilon=1.0, rng=random.Random(3))
    decision = policy.propose(state)
    assert "exploration" in decision.reason


# ---------------------------------------------------------------------------
# train_dqn(): runs, produces typed results
# ---------------------------------------------------------------------------


def test_train_dqn_runs_and_returns_expected_episode_count():
    result = _tiny_train()
    assert isinstance(result, TrainingRunResult)
    assert len(result.episodes) == 3
    assert all(isinstance(ep, TrainingEpisodeRecord) for ep in result.episodes)


def test_train_dqn_rejects_empty_training_scenarios():
    with pytest.raises(ValueError, match="training_scenarios"):
        _tiny_train(training_scenarios=())


def test_train_dqn_cycles_through_multiple_scenarios():
    result = _tiny_train(training_scenarios=TRAINING_SCENARIOS, episodes=4)
    scenario_names = {ep.scenario_name for ep in result.episodes}
    assert scenario_names == {s.name for s in TRAINING_SCENARIOS}


def test_loss_history_grows_once_replay_has_enough_samples():
    result = _tiny_train(batch_size=4, replay_capacity=50)
    assert len(result.loss_history) > 0
    assert all(isinstance(loss, float) and loss == loss for loss in result.loss_history)  # no NaN


def test_epsilon_decays_across_episodes():
    result = _tiny_train(epsilon_start=1.0, epsilon_end=0.1, epsilon_decay_episodes=3, episodes=3)
    epsilons = [ep.epsilon_used for ep in result.episodes]
    assert epsilons[0] > epsilons[-1]
    assert epsilons[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_training_run_result_carries_simulation_metadata():
    result = _tiny_train()
    assert result.execution_mode == "simulation"
    assert result.data_source == "synthetic"
    assert result.model_status == "diagnostic_unvalidated"
    assert EXECUTION_MODE == "simulation"


def test_episode_record_carries_simulation_metadata():
    result = _tiny_train()
    for ep in result.episodes:
        assert ep.execution_mode == "simulation"
        assert ep.data_source == "synthetic"
        assert ep.model_status == "diagnostic_unvalidated"


def test_hyperparameters_are_recorded_for_reproducibility():
    result = _tiny_train(seed=42)
    assert result.hyperparameters["seed"] == 42
    assert result.hyperparameters["hidden_size"] == 4


# ---------------------------------------------------------------------------
# Requested vs. approved actions, fallback accounting
# ---------------------------------------------------------------------------


def test_episode_records_carry_both_action_histograms():
    result = _tiny_train()
    for ep in result.episodes:
        assert isinstance(ep.requested_action_histogram, dict)
        assert isinstance(ep.approved_action_histogram, dict)
        assert sum(ep.approved_action_histogram.values()) == ep.step_count


def test_fallback_rate_is_consistent_with_fallback_count():
    result = _tiny_train()
    for ep in result.episodes:
        if ep.step_count:
            assert ep.fallback_rate == pytest.approx(ep.fallback_count / ep.step_count)
        else:
            assert ep.fallback_rate == 0.0


def test_termination_cause_is_a_known_value():
    result = _tiny_train()
    for ep in result.episodes:
        assert ep.termination_cause in ("trajectory_exhausted", "safe_stop")


# ---------------------------------------------------------------------------
# Reward handling: total=None must raise, not be silently handled
# ---------------------------------------------------------------------------


def test_train_dqn_raises_if_environment_reward_is_unweighted(monkeypatch):
    """Simulate a misconfigured environment (reward_weights=None) by
    monkeypatching _build_environment to omit reward_weights -- proves
    train_dqn() surfaces this loudly rather than routing around it."""
    import edge.eval.rl_training as module

    original_build = module._build_environment

    def _build_without_weights(scenario):
        env = original_build(scenario)
        env._reward_weights = None  # force unweighted mode for this test only
        return env

    monkeypatch.setattr(module, "_build_environment", _build_without_weights)

    with pytest.raises(ValueError, match="RewardResult"):
        _tiny_train()


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------


def test_identical_training_runs_are_deterministic():
    first = _tiny_train(seed=99)
    second = _tiny_train(seed=99)
    assert len(first.episodes) == len(second.episodes)
    for ep_a, ep_b in zip(first.episodes, second.episodes, strict=True):
        assert ep_a.cumulative_reward == ep_b.cumulative_reward
        assert ep_a.step_count == ep_b.step_count
        assert ep_a.requested_action_histogram == ep_b.requested_action_histogram
        assert ep_a.approved_action_histogram == ep_b.approved_action_histogram
    assert first.loss_history == second.loss_history


def test_different_seeds_can_diverge():
    first = _tiny_train(seed=1)
    second = _tiny_train(seed=2)
    # Not asserting they MUST differ (small nets can coincide), only that
    # the seed is actually threaded through -- covered by the determinism
    # test above; this just documents intent without being flaky.
    assert isinstance(first.loss_history, tuple)
    assert isinstance(second.loss_history, tuple)


# ---------------------------------------------------------------------------
# Training/evaluation scenario separation
# ---------------------------------------------------------------------------


def test_training_and_evaluation_scenarios_are_disjoint():
    training_names = {s.name for s in TRAINING_SCENARIOS}
    evaluation_names = {s.name for s in EVALUATION_SCENARIOS}
    assert training_names.isdisjoint(evaluation_names)


def test_training_and_evaluation_scenarios_use_different_seeds():
    training_seeds = {s.seed for s in TRAINING_SCENARIOS}
    evaluation_seeds = {s.seed for s in EVALUATION_SCENARIOS}
    assert training_seeds.isdisjoint(evaluation_seeds)


def test_evaluation_scenarios_reuse_the_existing_baseline_scenarios():
    assert SCENARIO_CLEAN_DEGRADATION in EVALUATION_SCENARIOS
    assert SCENARIO_INJECTED_CURRENT_SPIKE in EVALUATION_SCENARIOS


# ---------------------------------------------------------------------------
# evaluate_greedy(): comparison with baselines
# ---------------------------------------------------------------------------


def test_evaluate_greedy_runs_on_a_held_out_scenario():
    result = _tiny_train()
    record = evaluate_greedy(result.final_policy_net, SCENARIO_CLEAN_DEGRADATION)
    assert isinstance(record, TrainingEpisodeRecord)
    assert record.epsilon_used == 0.0
    assert record.mean_training_loss is None


def test_evaluate_greedy_is_comparable_to_existing_baselines():
    from edge.eval.rl_baseline_eval import run_baseline_policy_episode, run_pure_fallback_episode

    result = _tiny_train()
    dqn_record = evaluate_greedy(result.final_policy_net, SCENARIO_CLEAN_DEGRADATION)
    baseline_record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    fallback_record = run_pure_fallback_episode(SCENARIO_CLEAN_DEGRADATION)
    # Comparable fields exist on all three -- the actual point of reusing
    # the same scenario for all three runs.
    for record in (dqn_record, baseline_record, fallback_record):
        assert isinstance(record.cumulative_reward, float)
        assert isinstance(record.fallback_rate, float)


def test_evaluate_greedy_raises_if_reward_unweighted(monkeypatch):
    import edge.eval.rl_training as module

    original_build = module._build_environment

    def _build_without_weights(scenario):
        env = original_build(scenario)
        env._reward_weights = None
        return env

    monkeypatch.setattr(module, "_build_environment", _build_without_weights)
    net = _DQNNet(hidden_size=4)

    with pytest.raises(ValueError, match="RewardResult"):
        evaluate_greedy(net, SCENARIO_CLEAN_DEGRADATION)


# ---------------------------------------------------------------------------
# No hardware or external side effects; no over-claimed validation
# ---------------------------------------------------------------------------


def test_module_has_no_actuator_gpio_network_or_isolation_side_effects():
    import edge.eval.rl_training as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    forbidden_names = (
        "RelayController",
        "FakeActuator",
        "SelfHealOrchestrator",
        "process_isolated_channels",
        "paho",
    )
    for forbidden in forbidden_names:
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


def test_module_never_claims_validation_or_production_readiness():
    import edge.eval.rl_training as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "hardware-validated" not in content
    assert "validated for production" not in content
    assert "this policy is validated" not in content
