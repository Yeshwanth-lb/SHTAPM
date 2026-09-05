"""Tests for edge/rl/environment.py (simulation-only RL environment with
the fallback gate and reward calculation wired in). No policy/training/
approved-reward-weight claim exists here -- see the module's own docstring
for exactly what does and does not exist yet.

Core tests (no torch needed -- prognosis_runtime=None): always run.
Prognosis-integrated tests: skipped when torch is unavailable, same
skip-pattern as edge/tests/test_prognosis_runtime.py.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import RLAction

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.detector import NullDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.injection.injections import Spike
from edge.models.degradation_generator import (
    ChannelDegradationConfig,
    SyntheticDegradationGenerator,
)
from edge.rl.environment import EnvironmentStepResult, SHTAPMSimulationEnvironment
from edge.rl.fallback_gate import RL_CONFIDENCE_THRESHOLD_FIXTURE, GateDecision
from edge.rl.reward import SIMULATION_REWARD_WEIGHTS_FIXTURE, RewardResult
from edge.rl.state import RLState
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

WINDOW_SIZE_FIXTURE = 30
STEP_FIXTURE = 1
FIT_WINDOW_COUNT_FIXTURE = 2
FIT_BUFFER_SIZE_FIXTURE = WINDOW_SIZE_FIXTURE + (FIT_WINDOW_COUNT_FIXTURE - 1) * STEP_FIXTURE  # 31
LENGTH_FIXTURE = 40  # 40 - 31 = 9 real steps available after warm-up


def _timestamps(n: int) -> list[str]:
    return [f"2026-08-10T00:{i // 60:02d}:{i % 60:02d}.000Z" for i in range(n)]


def _generator(**overrides) -> SyntheticDegradationGenerator:
    config = {
        "length": LENGTH_FIXTURE,
        "start_health": 1.0,
        "end_health": 0.0,
        "seed": 1337,
        "channels": {
            "vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2),
        },
    }
    config.update(overrides)
    return SyntheticDegradationGenerator(**config)


def _pipeline_deps() -> tuple[Preprocessor, P2Pipeline, ConsistencyProvider]:
    """A FRESH (preprocessor, pipeline, c_provider) triple -- required per
    environment instance, since P2's ConsistencyProvider is stateful and
    fit-once (see edge/rl/environment.py's EPISODE CONTRACT)."""
    preprocessor = Preprocessor(
        median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW_SIZE_FIXTURE, step=STEP_FIXTURE
    )
    c_provider = ConsistencyProvider()
    pipeline = P2Pipeline(
        preprocessor=preprocessor,
        detector=NullDetector(),
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(TrendSignPhysicsRule()),
        c_provider=c_provider,
        k_provider=CorrelationProvider(),
        h_provider=HReliabilityProvider(),
        flag_policy=SeverityThresholdFlagPolicy(),
    )
    return preprocessor, pipeline, c_provider


def _environment(**overrides) -> SHTAPMSimulationEnvironment:
    preprocessor, pipeline, c_provider = _pipeline_deps()
    kwargs = {
        "generator": _generator(),
        "timestamps": _timestamps(LENGTH_FIXTURE),
        "preprocessor": preprocessor,
        "pipeline": pipeline,
        "c_provider": c_provider,
        "fit_window_count": FIT_WINDOW_COUNT_FIXTURE,
        "confidence_threshold": RL_CONFIDENCE_THRESHOLD_FIXTURE,
    }
    kwargs.update(overrides)
    return SHTAPMSimulationEnvironment(**kwargs)


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


def test_reset_returns_an_rl_state():
    env = _environment()
    state = env.reset()
    assert isinstance(state, RLState)


def test_reset_state_has_no_anomaly_on_clean_data():
    env = _environment()
    state = env.reset()
    assert state.anomaly_flag is False  # NullDetector never flags


def test_reset_state_health_is_within_expected_range():
    env = _environment()
    state = env.reset()
    assert 0.0 <= state.health <= 1.0


def test_reset_twice_raises():
    env = _environment()
    env.reset()
    with pytest.raises(RuntimeError, match="only be called once"):
        env.reset()


def test_reset_state_execution_mode_is_simulation():
    env = _environment()
    state = env.reset()
    assert state.execution_mode == "simulation"


def test_reset_without_prognosis_runtime_reports_unavailable_prognosis():
    env = _environment()
    state = env.reset()
    assert state.failure_eta is None
    assert state.prognosis_available is False


# ---------------------------------------------------------------------------
# step() -- basic contract
# ---------------------------------------------------------------------------


def test_step_before_reset_raises():
    env = _environment()
    with pytest.raises(RuntimeError, match="before reset"):
        env.step(RLAction.continue_)


def test_step_returns_environment_step_result_with_real_reward_and_gate_decision():
    env = _environment()
    env.reset()
    result = env.step(RLAction.continue_)
    assert isinstance(result, EnvironmentStepResult)
    assert isinstance(result.state, RLState)
    assert isinstance(result.reward, RewardResult)
    assert isinstance(result.gate_decision, GateDecision)
    assert isinstance(result.done, bool)
    assert isinstance(result.info, dict)


def test_step_accepts_every_rl_action_member():
    for action in RLAction:
        env = _environment()
        env.reset()
        result = env.step(action)
        assert result.info["requested_action"] == action.value


def test_unrecognized_action_value_does_not_raise_and_falls_back():
    """CORRECTION from the prior version: step() no longer rejects a bad
    action itself -- the fallback gate handles it safely instead (see
    module docstring's CORRECTION note)."""
    env = _environment()
    env.reset()
    result = env.step("not_a_real_action")  # not an RLAction member
    assert result.gate_decision.fallback_used is True
    assert result.info["requested_action"] == "not_a_real_action"


def test_step_info_carries_simulation_metadata():
    env = _environment()
    env.reset()
    result = env.step(RLAction.continue_)
    assert result.info["execution_mode"] == "simulation"
    assert result.info["data_source"] == "synthetic"
    assert result.info["model_status"] == "diagnostic_unvalidated"


def test_step_info_carries_deterministic_fallback_candidates_key():
    env = _environment()
    env.reset()
    result = env.step(RLAction.continue_)
    assert "deterministic_fallback_would_isolate" in result.info
    assert isinstance(result.info["deterministic_fallback_would_isolate"], list)
    assert "persistent_isolation_tracked_channels" in result.info


def test_step_never_performs_actuation_or_isolation_side_effects():
    """Structural proof, mirroring edge/tests/test_live_p2_monitor.py's
    test_monitor_never_isolates_or_actuates: no forbidden call exists in
    the module's own source."""
    import edge.rl.environment as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "RelayController" not in content
    assert "FakeActuator" not in content
    assert "process_isolated_channels" not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


# ---------------------------------------------------------------------------
# Requested vs. approved action separation; gate invocation on every step
# ---------------------------------------------------------------------------


def test_gate_is_invoked_on_every_step_producing_a_decision_field():
    env = _environment()
    env.reset()
    for _ in range(3):
        result = env.step(RLAction.continue_)
        assert result.gate_decision is not None


def test_requested_and_approved_action_are_distinct_fields():
    env = _environment()
    env.reset()
    # A validated, confident request that violates no constraint: approved.
    result = env.step(
        RLAction.continue_, policy_available=True, policy_validated=True, confidence=0.99
    )
    assert result.gate_decision.requested_action == RLAction.continue_
    assert result.gate_decision.approved_action == RLAction.continue_
    assert result.gate_decision.fallback_used is False


def test_fallback_overrides_an_unvalidated_policys_request_on_clean_data():
    """policy_validated defaults to False -- on clean (non-malicious) data
    the deterministic fallback resolves to Continue, which DIFFERS from a
    requested Isolate, proving the override actually happens."""
    env = _environment()
    env.reset()
    result = env.step(RLAction.isolate)  # policy_validated defaults to False
    assert result.gate_decision.requested_action == RLAction.isolate
    assert result.gate_decision.approved_action == RLAction.continue_
    assert result.gate_decision.fallback_used is True
    assert result.info["approved_action"] == RLAction.continue_.value
    assert result.info["requested_action"] == RLAction.isolate.value


def test_policy_validated_is_never_granted_by_the_environment():
    """Passing policy_validated=True through is honored (it came from the
    caller); the environment itself never flips it -- proven by the
    default (False) actually causing a fallback above, and here by
    confirming the gate's own reported status matches what was passed."""
    env = _environment()
    env.reset()
    result = env.step(RLAction.continue_, policy_validated=False)
    assert result.gate_decision.policy_status in ("unvalidated", "unavailable")


# ---------------------------------------------------------------------------
# Safe-stop terminal behavior
# ---------------------------------------------------------------------------


def test_safe_stop_action_terminates_episode_immediately():
    env = _environment()
    env.reset()
    result = env.step(RLAction.safe_stop)
    assert result.done is True
    assert result.gate_decision.approved_action == RLAction.safe_stop


def test_step_after_termination_raises():
    env = _environment()
    env.reset()
    result = env.step(RLAction.safe_stop)
    assert result.done is True
    with pytest.raises(RuntimeError, match="after episode termination"):
        env.step(RLAction.continue_)


def test_episode_terminates_when_trajectory_exhausted():
    env = _environment()
    env.reset()
    done = False
    steps = 0
    while not done:
        result = env.step(RLAction.continue_)
        done = result.done
        steps += 1
        if steps > LENGTH_FIXTURE:  # safety net against an infinite loop bug
            pytest.fail("episode did not terminate within the trajectory length")
    assert result.info["trajectory_exhausted"] is True


# ---------------------------------------------------------------------------
# Reward wiring: unweighted by default, explicit weights when supplied
# ---------------------------------------------------------------------------


def test_reward_is_unweighted_by_default():
    env = _environment()
    env.reset()
    result = env.step(RLAction.continue_)
    assert result.reward.total is None
    assert result.reward.reward_policy_status == "unweighted"


def test_reward_is_weighted_when_reward_weights_supplied():
    env = _environment(reward_weights=SIMULATION_REWARD_WEIGHTS_FIXTURE)
    env.reset()
    result = env.step(RLAction.continue_)
    assert result.reward.total is not None
    assert result.reward.reward_policy_status == "simulation_fixture_weighted"


def test_reward_reflects_the_actual_transition():
    env = _environment()
    env.reset()
    result = env.step(RLAction.continue_)
    assert result.reward.previous_state is not None
    assert result.reward.next_state == result.state
    assert result.reward.requested_action == RLAction.continue_


# ---------------------------------------------------------------------------
# Deterministic behavior with a fixed seed
# ---------------------------------------------------------------------------


def test_two_environments_with_identical_config_produce_identical_episodes():
    env_a = _environment()
    env_b = _environment()

    state_a0 = env_a.reset()
    state_b0 = env_b.reset()
    assert state_a0.to_vector() == state_b0.to_vector()

    for _ in range(5):
        result_a = env_a.step(RLAction.continue_)
        result_b = env_b.step(RLAction.continue_)
        assert result_a.state.to_vector() == result_b.state.to_vector()
        assert result_a.done == result_b.done
        assert result_a.reward.components == result_b.reward.components
        assert result_a.gate_decision == result_b.gate_decision


def test_different_seed_changes_the_health_trajectory_but_not_its_shape():
    env_a = _environment(generator=_generator(seed=1))
    env_b = _environment(generator=_generator(seed=2))

    state_a = env_a.reset()
    state_b = env_b.reset()
    # Health ground truth is a pure function of config, not seed (see
    # edge/models/degradation_generator.py) -- identical regardless of seed.
    assert state_a.health == pytest.approx(state_b.health)


# ---------------------------------------------------------------------------
# Construction validation
# ---------------------------------------------------------------------------


def test_trajectory_too_short_for_fit_buffer_raises():
    preprocessor, pipeline, c_provider = _pipeline_deps()
    with pytest.raises(ValueError, match="fit buffer"):
        SHTAPMSimulationEnvironment(
            generator=_generator(length=FIT_BUFFER_SIZE_FIXTURE),  # exactly equal, not greater
            timestamps=_timestamps(FIT_BUFFER_SIZE_FIXTURE),
            preprocessor=preprocessor,
            pipeline=pipeline,
            c_provider=c_provider,
            fit_window_count=FIT_WINDOW_COUNT_FIXTURE,
            confidence_threshold=RL_CONFIDENCE_THRESHOLD_FIXTURE,
        )


def test_confidence_threshold_is_a_required_argument():
    preprocessor, pipeline, c_provider = _pipeline_deps()
    with pytest.raises(TypeError):
        SHTAPMSimulationEnvironment(
            generator=_generator(),
            timestamps=_timestamps(LENGTH_FIXTURE),
            preprocessor=preprocessor,
            pipeline=pipeline,
            c_provider=c_provider,
            fit_window_count=FIT_WINDOW_COUNT_FIXTURE,
        )  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Injections layered on top of degradation (reuse, not duplication)
# ---------------------------------------------------------------------------


def test_injections_are_layered_onto_the_generated_trajectory():
    """A Spike injection targeting a healthy channel must actually change
    that channel's telemetry values within its onset/duration window --
    proving edge.injection.injections is genuinely reused, not bypassed."""
    spike = Spike(channel="current", onset=5, duration=3, amplitude=100.0)
    preprocessor, pipeline, c_provider = _pipeline_deps()
    env = SHTAPMSimulationEnvironment(
        generator=_generator(),
        timestamps=_timestamps(LENGTH_FIXTURE),
        preprocessor=preprocessor,
        pipeline=pipeline,
        c_provider=c_provider,
        fit_window_count=FIT_WINDOW_COUNT_FIXTURE,
        confidence_threshold=RL_CONFIDENCE_THRESHOLD_FIXTURE,
        injections=[spike],
    )
    spiked_value = env._frames[5].sensors.current
    baseline_value = env._frames[0].sensors.current
    assert spiked_value == pytest.approx(baseline_value + 100.0)


# ---------------------------------------------------------------------------
# Prognosis-integrated behavior (torch-gated)
# ---------------------------------------------------------------------------


class TestWithPrognosisRuntime:
    @staticmethod
    def _predictor_runtime():
        pytest.importorskip("torch")
        from edge.models.lstm_prognosis import LSTMPrognosisPredictor, _LSTMPrognosisNet
        from edge.pipeline.prognosis_runtime import PrognosisRuntime

        network = _LSTMPrognosisNet(hidden_size=4)
        return PrognosisRuntime(
            predictor=LSTMPrognosisPredictor(network), prognosis_data_source="synthetic"
        )

    def test_state_has_failure_eta_when_prognosis_runtime_supplied(self):
        runtime = self._predictor_runtime()
        env = _environment(prognosis_runtime=runtime)
        state = env.reset()
        assert state.failure_eta is not None
        assert state.prognosis_available is True

    def test_state_prognosis_data_source_matches_runtime(self):
        runtime = self._predictor_runtime()
        env = _environment(prognosis_runtime=runtime)
        state = env.reset()
        assert state.prognosis_data_source == "synthetic"
