"""RL deterministic-baseline evaluation harness (DIAGNOSTIC ONLY --
simulation-first RL pathway). No RL training, no learned policy, no
composition-root wiring exists here or anywhere yet.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

Same status as ``edge/eval/twin_training.py``/``edge/eval/synthetic_
prognosis_training.py``: not on pytest ``testpaths``' production path, not
wired into any acceptance criterion, not part of ``edge/pipeline/cycle.py``
or any P2/P3 production wiring, no new dependency.

PURPOSE: establish two REFERENCE baselines against which a future trained
RL policy could eventually be compared -- neither baseline here IS, or is
presented as, a trained/learned policy:

  1. ``run_baseline_policy_episode``: the existing, already-implemented
     ``edge.rl.policy.BaselinePolicy`` (a deterministic rule set, NOT
     learned intelligence -- see that module's own docstring) proposes an
     action every cycle; the existing, unmodified fallback gate and
     reward module decide what actually happens and how it scores.
  2. ``run_pure_fallback_episode``: NO policy at all.
     ``policy_available=False`` on every single step -- exactly PRD
     FR-RL4 / acceptance criterion P3-RL-S1's own named scenario
     ("Trained policy file missing -> Rule-based fallback engages").

Both baselines run through the SAME, real, unmodified
``edge.rl.environment.SHTAPMSimulationEnvironment`` -- every step still
calls ``edge.rl.fallback_gate.evaluate_rl_action()`` (never bypassed) and
``edge.rl.reward.compute_reward()`` (never bypassed). This module adds NO
new isolation, safety, reward, or transition logic of its own -- it only
drives the existing pieces and records what they produced.

REQUESTED ACTION FOR THE PURE-FALLBACK BASELINE: ``None`` is passed as
the requested action, not a fabricated ``RLAction`` member -- "no policy
exists" is honestly represented as "no action was requested", which is
exactly what ``edge.rl.fallback_gate.evaluate_rl_action()`` already
supports (its own ``requested_action`` parameter is typed
``RLAction | None``); ``SHTAPMSimulationEnvironment.step()`` passes its
``action`` argument straight through to that function unchanged, so this
requires no code change anywhere and is not a bypass of anything.

REWARD WEIGHTING: both baselines are run with
``edge.rl.reward.SIMULATION_REWARD_WEIGHTS_FIXTURE`` (uniform 1.0-per-
component, explicitly NOT a tuned/research value -- see that module's own
docstring) supplied EXPLICITLY to the environment, so every transition's
reward total is a real scalar (never ``None``) and episodes are directly
comparable. This module invents no new weight set.

SCENARIOS: a small, fixed, named set of ``ScenarioConfig`` values (see
below), each fully specifying the synthetic degradation generator's
config (seed, length, start/end health, degradation rate, per-channel
config) plus any ``edge.injection.injections`` layered on top. Nothing
here claims, or should be read as claiming, that these scenarios
represent real pump/sensor behavior -- they are simulation fixtures, for
exactly the reasons ``edge/models/degradation_generator.py`` and
``edge/injection/injections.py`` already document for their own values.

DETERMINISM: every scenario's timestamps are a pure function of its
length (no wall clock, same helper convention as every other test/eval
module in this project); a fresh P2 pipeline/``ConsistencyProvider`` pair
and a fresh generator are built per episode run from the scenario's own
config, so two calls with the same ``ScenarioConfig`` produce byte-
identical ``EpisodeRecord``s (verified by this module's own tests).

NO PROGNOSIS RUNTIME IS WIRED IN: this harness does not construct or pass
an ``edge.pipeline.prognosis_runtime.PrognosisRuntime`` -- keeping it
free of the transitive torch dependency that module carries. Every
recorded ``failure_eta`` is therefore honestly ``None`` throughout (see
``edge.rl.state``'s own missing-prognosis handling) -- this is a real
scope limitation of this harness, not a defect.

NOT A VALIDATION CLAIM: nothing in this module marks either baseline
"validated", "production-ready", "accurate", or "safe for real-world
actuation" -- see ``EpisodeRecord``'s fixed metadata fields. Both
baselines' entire purpose is to be a REFERENCE POINT for a future trained
policy, not a claim about real system behavior.

ACTION-DEPENDENT TRANSITION (this module's environment dependency, not
this module's own logic): ``edge/rl/environment.py`` now applies a
held-last-value substitution for tracked-and-isolated channels and skips
the transition entirely on an approved safe-stop (see that module's own
ACTION-DEPENDENT TRANSITION docstring section). Every ``TransitionRecord``
here therefore also carries ``transition_consumed``,
``substituted_channels``, and ``transition_substitution_mode`` -- and
every ``EpisodeRecord`` carries ``comparison_caveat``
(``ACTION_DEPENDENT_COMPARISON_CAVEAT``): a reward difference between two
episodes may now reflect both decision quality and the resulting
simulated observation path, not decision quality alone, since two
baselines can diverge into different observed telemetry once their
approved actions differ.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass

from app.schemas.contracts import RLAction

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.detector import NullDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.injection.injections import Injection, Spike
from edge.models.degradation_generator import (
    ChannelDegradationConfig,
    SyntheticDegradationGenerator,
)
from edge.rl.environment import SHTAPMSimulationEnvironment
from edge.rl.fallback_gate import RL_CONFIDENCE_THRESHOLD_FIXTURE
from edge.rl.policy import BASELINE_CRITICAL_HEALTH_FIXTURE, BaselinePolicy
from edge.rl.reward import SIMULATION_REWARD_WEIGHTS_FIXTURE
from edge.rl.state import RLState
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"

# ---- Evaluation-harness fixtures (NOT scenario data) ----------------------
# Shared P2 plumbing constants -- identical across every scenario, mirroring
# edge/tests/test_rl_environment.py's own fixture convention.
WINDOW_SIZE_FIXTURE = 30
STEP_FIXTURE = 1
FIT_WINDOW_COUNT_FIXTURE = 2


@dataclass(frozen=True)
class ScenarioConfig:
    """One fully explicit, reproducible synthetic scenario. Every field
    that feeds ``SyntheticDegradationGenerator``/``edge.injection.injections``
    is named here -- nothing is inferred or defaulted at the call site."""

    name: str
    seed: int
    length: int
    start_health: float
    end_health: float
    degradation_rate: float
    channels: Mapping[str, ChannelDegradationConfig]
    injections: tuple[Injection, ...] = ()


# Two named, explicit, small scenarios -- see module docstring: simulation
# fixtures, not a claim about real pump/sensor behavior.
SCENARIO_CLEAN_DEGRADATION = ScenarioConfig(
    name="clean_degradation",
    seed=1337,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(),
)

SCENARIO_INJECTED_CURRENT_SPIKE = ScenarioConfig(
    name="injected_current_spike",
    seed=1338,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(Spike(channel="current", onset=32, duration=5, amplitude=50.0),),
)


def default_scenarios() -> tuple[ScenarioConfig, ...]:
    return (SCENARIO_CLEAN_DEGRADATION, SCENARIO_INJECTED_CURRENT_SPIKE)


@dataclass(frozen=True)
class TransitionRecord:
    """One step's full accounting -- see module docstring."""

    episode_index: int
    step_index: int
    previous_state_vector: tuple[float, ...]
    next_state_vector: tuple[float, ...]
    requested_action: str | None
    approved_action: str
    fallback_used: bool
    fallback_reason: str | None
    safety_status: str
    policy_status: str
    reward_components: dict[str, float]
    total_reward: float | None
    done: bool
    transition_consumed: bool
    safe_stop_terminated_without_transition: bool
    transition_substitution_mode: str | None
    substituted_channels: tuple[str, ...]
    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


# Recorded on every EpisodeRecord (see requirement to record the comparison
# caveat, not just document it in prose): once the environment's transition
# became action-dependent (edge/rl/environment.py's ACTION-DEPENDENT
# TRANSITION), two baselines run over the same ScenarioConfig can observe
# DIFFERENT simulated telemetry from each other whenever their approved
# actions differ (isolate substitutes; safe_stop skips the transition) --
# a reward difference between two EpisodeRecords therefore reflects BOTH
# decision quality AND the resulting simulated observation path, no longer
# decision quality alone. This was not true before this increment, when
# every baseline observed the identical precomputed trajectory regardless
# of its actions.
ACTION_DEPENDENT_COMPARISON_CAVEAT = (
    "Reward differences between EpisodeRecords may now reflect both decision "
    "quality and the resulting simulated observation path (substitution/"
    "safe-stop), not decision quality alone -- see edge/rl/environment.py's "
    "ACTION-DEPENDENT TRANSITION section."
)


@dataclass(frozen=True)
class EpisodeRecord:
    """One baseline's one-episode summary over one scenario -- see module
    docstring's NOT A VALIDATION CLAIM section."""

    baseline_name: str
    scenario_name: str
    scenario_config: ScenarioConfig
    cumulative_reward: float
    step_count: int
    termination_cause: str  # "trajectory_exhausted" | "safe_stop"
    fallback_count: int
    fallback_rate: float
    requested_action_histogram: dict[str, int]
    approved_action_histogram: dict[str, int]
    final_health: float | None
    final_failure_eta: float | None
    reward_policy_status: str
    transitions: tuple[TransitionRecord, ...]
    comparison_caveat: str = ACTION_DEPENDENT_COMPARISON_CAVEAT
    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def _timestamps(n: int) -> list[str]:
    """Deterministic, no wall clock -- same convention as every other
    test/eval module in this project."""
    return [f"2026-08-10T00:{i // 60:02d}:{i % 60:02d}.000Z" for i in range(n)]


def _build_p2_pipeline() -> tuple[Preprocessor, P2Pipeline, ConsistencyProvider]:
    """A FRESH (preprocessor, pipeline, c_provider) triple -- required per
    episode, since P2's ConsistencyProvider is stateful and fit-once (see
    edge/rl/environment.py's EPISODE CONTRACT)."""
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


def _build_environment(scenario: ScenarioConfig) -> SHTAPMSimulationEnvironment:
    generator = SyntheticDegradationGenerator(
        length=scenario.length,
        start_health=scenario.start_health,
        end_health=scenario.end_health,
        degradation_rate=scenario.degradation_rate,
        seed=scenario.seed,
        channels=scenario.channels,
    )
    preprocessor, pipeline, c_provider = _build_p2_pipeline()
    return SHTAPMSimulationEnvironment(
        generator=generator,
        timestamps=_timestamps(scenario.length),
        preprocessor=preprocessor,
        pipeline=pipeline,
        c_provider=c_provider,
        fit_window_count=FIT_WINDOW_COUNT_FIXTURE,
        confidence_threshold=RL_CONFIDENCE_THRESHOLD_FIXTURE,
        injections=scenario.injections,
        reward_weights=SIMULATION_REWARD_WEIGHTS_FIXTURE,
    )


def _action_label(action: object) -> str | None:
    if action is None:
        return None
    if isinstance(action, RLAction):
        return action.value
    return str(action)


_ProposeFn = Callable[[RLState], "tuple[RLAction | None, bool, bool, float | None]"]


def _run_episode(
    scenario: ScenarioConfig,
    baseline_name: str,
    *,
    propose_action: _ProposeFn,
) -> EpisodeRecord:
    """Shared episode-driving loop for both baselines. ``propose_action``
    is called once per step with the CURRENT ``RLState`` and must return
    ``(action, policy_available, policy_validated, confidence)`` -- the
    exact keyword shape ``SHTAPMSimulationEnvironment.step()`` already
    accepts. Neither baseline's own action-selection logic lives here;
    this function only drives the loop and records results."""
    env = _build_environment(scenario)
    state = env.reset()

    transitions: list[TransitionRecord] = []
    step_index = 0
    done = False
    last_info: dict[str, object] = {}
    last_reward_policy_status = "unweighted"

    while not done:
        action, policy_available, policy_validated, confidence = propose_action(state)
        result = env.step(
            action,
            policy_available=policy_available,
            policy_validated=policy_validated,
            confidence=confidence,
        )
        transitions.append(
            TransitionRecord(
                episode_index=0,
                step_index=step_index,
                previous_state_vector=state.to_vector(),
                next_state_vector=result.state.to_vector(),
                requested_action=_action_label(result.gate_decision.requested_action),
                approved_action=result.gate_decision.approved_action.value,
                fallback_used=result.gate_decision.fallback_used,
                fallback_reason=result.gate_decision.fallback_reason,
                safety_status=result.gate_decision.safety_status,
                policy_status=result.gate_decision.policy_status,
                reward_components=asdict(result.reward.components),
                total_reward=result.reward.total,
                done=result.done,
                transition_consumed=bool(result.info["transition_consumed"]),
                safe_stop_terminated_without_transition=bool(
                    result.info["safe_stop_terminated_without_transition"]
                ),
                transition_substitution_mode=result.info["transition_substitution_mode"],
                substituted_channels=tuple(result.info["substituted_channels"]),
            )
        )
        state = result.state
        done = result.done
        last_info = result.info
        last_reward_policy_status = result.reward.reward_policy_status
        step_index += 1

    fallback_count = sum(1 for t in transitions if t.fallback_used)
    step_count = len(transitions)
    termination_cause = (
        "trajectory_exhausted" if last_info.get("trajectory_exhausted") else "safe_stop"
    )
    requested_histogram = Counter(t.requested_action or "none" for t in transitions)
    approved_histogram = Counter(t.approved_action for t in transitions)
    cumulative_reward = sum(t.total_reward for t in transitions if t.total_reward is not None)

    return EpisodeRecord(
        baseline_name=baseline_name,
        scenario_name=scenario.name,
        scenario_config=scenario,
        cumulative_reward=cumulative_reward,
        step_count=step_count,
        termination_cause=termination_cause,
        fallback_count=fallback_count,
        fallback_rate=(fallback_count / step_count) if step_count else 0.0,
        requested_action_histogram=dict(requested_histogram),
        approved_action_histogram=dict(approved_histogram),
        final_health=state.health,
        final_failure_eta=state.failure_eta,
        reward_policy_status=last_reward_policy_status,
        transitions=tuple(transitions),
    )


def run_baseline_policy_episode(scenario: ScenarioConfig) -> EpisodeRecord:
    """Run ``edge.rl.policy.BaselinePolicy`` (the existing, unmodified
    deterministic rule set) through one scenario."""
    policy = BaselinePolicy(critical_health_threshold=BASELINE_CRITICAL_HEALTH_FIXTURE)

    def _propose(state):
        decision = policy.propose(state)
        return (
            decision.proposed_action,
            decision.policy_available,
            decision.policy_validated,
            decision.confidence,
        )

    return _run_episode(scenario, "baseline_policy", propose_action=_propose)


def run_pure_fallback_episode(scenario: ScenarioConfig) -> EpisodeRecord:
    """Run with NO policy at all -- ``policy_available=False`` on every
    step (FR-RL4 / P3-RL-S1's own scenario). ``None`` is passed as the
    requested action -- see module docstring's REQUESTED ACTION section
    for why this is not a fabrication or a gate bypass."""

    def _propose(_state):
        return (None, False, False, None)

    return _run_episode(scenario, "pure_fallback", propose_action=_propose)


def run_all_baselines(
    scenarios: Sequence[ScenarioConfig] | None = None,
) -> list[EpisodeRecord]:
    """Run both baselines over every scenario (default: ``default_scenarios()``).
    Small callable diagnostic entry point -- NOT a production composition-root
    integration."""
    scenarios = scenarios if scenarios is not None else default_scenarios()
    records: list[EpisodeRecord] = []
    for scenario in scenarios:
        records.append(run_baseline_policy_episode(scenario))
        records.append(run_pure_fallback_episode(scenario))
    return records


def main() -> None:
    """Diagnostic entry point: ``python -m edge.eval.rl_baseline_eval``.
    Prints a concise summary of both baselines over the default scenarios.
    NOT a validation claim -- see module docstring."""
    print("=== RL deterministic-baseline evaluation (diagnostic, simulation-only) ===")
    for record in run_all_baselines():
        print(
            f"[{record.scenario_name}] {record.baseline_name}: "
            f"steps={record.step_count} cumulative_reward={record.cumulative_reward:.3f} "
            f"fallback_rate={record.fallback_rate:.2f} "
            f"termination={record.termination_cause} "
            f"final_health={record.final_health}"
        )
    print(
        "NOTE: both baselines are deterministic, non-learned reference points "
        "on SYNTHETIC data (data_source=synthetic, execution_mode=simulation, "
        "model_status=diagnostic_unvalidated). Neither is validated, "
        "production-ready, or safe for real-world actuation."
    )


if __name__ == "__main__":
    main()
