"""Simulation-only DQN training harness (DIAGNOSTIC ONLY -- FR-RL1-4). No
composition-root wiring, no production policy, no real-world validation
claim exists here or anywhere in this pathway.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

Same status as ``edge/eval/twin_training.py``/``edge/eval/synthetic_
prognosis_training.py``/``edge/eval/rl_baseline_eval.py``: not on pytest
``testpaths``' production path, not wired into any acceptance criterion,
not part of ``edge/pipeline/cycle.py`` or any P2/P3 production wiring, no
new dependency (``torch`` is already used by ``edge/models/lstm_twin.py``/
``edge/models/lstm_prognosis.py``).

ALGORITHM: DQN -- a small MLP (``STATE_WIDTH`` inputs -> ``len(RLAction)``
Q-values), a replay buffer, and a periodically-copied target network. This
mirrors Doc06's own suggested reference ("Implement RL agent (DQN) over
the state vector + reward"), but that line is Doc06's suggestion, NOT a
DECISIONS.md-recorded, approved architecture decision -- no such entry
exists for RL algorithm choice. DQN is used here as the smallest algorithm
matching the current 9-dimensional continuous observation / 5-action
discrete action space, per this project's own read-only architecture
review preceding this increment -- not presented as a final or approved
choice.

REUSE, NOT DUPLICATION: this module adds no new state, environment,
reward, gate, or policy logic. It wires together, unmodified:
  - ``edge.rl.state`` (``STATE_WIDTH``, ``RLState``)
  - ``edge.rl.environment.SHTAPMSimulationEnvironment`` (unmodified;
    ``reward_weights`` is supplied explicitly -- see REWARD HANDLING)
  - ``edge.rl.policy.Policy``/``PolicyDecision`` (this module's
    ``DQNPolicy`` implements the same Protocol ``BaselinePolicy`` does)
  - ``edge.rl.fallback_gate``/``edge.rl.reward`` (via the environment;
    never called directly, never bypassed)
  - ``edge.eval.rl_baseline_eval`` (``ScenarioConfig``,
    ``run_baseline_policy_episode``, ``run_pure_fallback_episode`` -- for
    comparison in ``main()`` only, never modified)

POLICY VALIDATION IS NEVER GRANTED HERE: ``DQNPolicy`` always reports
``policy_validated=False`` (see ``edge/rl/policy.py``'s own convention for
``BaselinePolicy``) -- no training process defined anywhere in this
project constitutes real validation. This means a DQN policy's own
non-safe_stop requests are gated exactly like ``BaselinePolicy``'s are
today: subject to override by ``edge.rl.fallback_gate.evaluate_rl_action``
whenever the deterministic assessment disagrees. Training proceeds
against ``requested_action``-scored reward regardless (see
``edge/rl/reward.py``'s own anti-gate-exploitation rationale, unchanged),
so this is expected, not a defect to fix.

REWARD HANDLING: every training environment is constructed with
``reward_weights=edge.rl.reward.SIMULATION_REWARD_WEIGHTS_FIXTURE`` (the
existing uniform 1.0-per-component fixture -- NOT a new or tuned weight
set). ``train_dqn()`` RAISES if any ``RewardResult.total`` is ``None``
(i.e. if an environment were ever misconfigured without reward weights) --
this is a configuration error to surface immediately, never a runtime
condition to silently route around.

TRAINING/EVALUATION SCENARIO SEPARATION: ``TRAINING_SCENARIOS`` (below)
are distinct, differently-seeded ``ScenarioConfig``s the network is
actually trained on. Comparison in ``main()`` uses
``edge.eval.rl_baseline_eval``'s existing ``SCENARIO_CLEAN_DEGRADATION``/
``SCENARIO_INJECTED_CURRENT_SPIKE`` as HELD-OUT evaluation scenarios --
never included in ``TRAINING_SCENARIOS`` -- mirroring the same leakage
discipline ``edge/eval/pronostia_prognosis_training.py``'s leave-one-
bearing-out split and ``edge/eval/synthetic_prognosis_training.py``'s own
train/eval convention already established elsewhere in this project.

ACTION-DEPENDENT TRANSITION LIMITATIONS (inherited from
``edge/rl/environment.py``, unchanged by this module): ``isolate`` only
ever affects whatever channel(s) the existing, unmodified
``IsolationFallbackTracker`` has already flagged (never RL-chosen, never
an arbitrary channel); ``reduce_weight`` remains a complete trajectory
no-op (no approved down-weighting formula exists anywhere in this
project); ``alert``/``continue_`` are no-ops; no twin reconstruction and
no health-recovery modeling exist. A DQN policy trained against this
environment can therefore only ever learn WHEN to request one of 5
actions given trust/health/anomaly signals -- with real environmental
feedback for only ``isolate`` (channel substitution) and ``safe_stop``
(episode termination); the other three actions are reward-scored but
world-inert. This is an honest, bounded first training target, not
something this module works around or hides.

WHAT THIS MODULE DOES NOT, AND CANNOT, ESTABLISH: any acceptable false-
isolation rate (U06, fully open); that a trained policy is "validated" in
the FR-RL4/gate sense (no validation process is defined anywhere in this
project); any real-world safety, accuracy, or production-readiness claim;
that ``SIMULATION_REWARD_WEIGHTS_FIXTURE`` reflects a correct real
priority ordering between objectives. Every claim this module's own
``main()`` prints is scoped to "the training loop mechanics run and
produce a trend on synthetic data" -- nothing more.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import torch
from app.schemas.contracts import RLAction

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.detector import NullDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.eval.rl_baseline_eval import (
    FIT_WINDOW_COUNT_FIXTURE,
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_CURRENT_SPIKE,
    STEP_FIXTURE,
    WINDOW_SIZE_FIXTURE,
    ScenarioConfig,
    run_baseline_policy_episode,
    run_pure_fallback_episode,
)
from edge.models.degradation_generator import (
    ChannelDegradationConfig,
    SyntheticDegradationGenerator,
)
from edge.rl.environment import SHTAPMSimulationEnvironment
from edge.rl.fallback_gate import RL_CONFIDENCE_THRESHOLD_FIXTURE
from edge.rl.policy import PolicyDecision
from edge.rl.reward import SIMULATION_REWARD_WEIGHTS_FIXTURE
from edge.rl.state import STATE_WIDTH, RLState
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"

DQN_POLICY_NAME = "dqn_diagnostic"
DQN_POLICY_VERSION = "0.1.0-unvalidated"

# Fixed, canonical ordering of RLAction members for indexing Q-values --
# Python's own Enum iteration order (definition order), named explicitly
# so it is never silently re-derived differently in two places.
ACTION_ORDER: tuple[RLAction, ...] = tuple(RLAction)

# ---- Training hyperparameters -- ALL diagnostic simulation fixtures, NOT
# tuned or research-approved values. Every train_dqn() argument is
# REQUIRED (no default in the function itself); these constants exist
# solely so main()'s own diagnostic run has one canonical, named copy. ----
HIDDEN_SIZE_FIXTURE = 16
LEARNING_RATE_FIXTURE = 0.001
GAMMA_FIXTURE = 0.99
EPSILON_START_FIXTURE = 1.0
EPSILON_END_FIXTURE = 0.05
EPSILON_DECAY_EPISODES_FIXTURE = 20
REPLAY_BUFFER_SIZE_FIXTURE = 2000
BATCH_SIZE_FIXTURE = 32
TARGET_UPDATE_INTERVAL_FIXTURE = 5  # episodes
TRAIN_EPISODES_FIXTURE = 30
SEED_FIXTURE = 1337

# Training scenarios -- distinct seeds/config from
# edge.eval.rl_baseline_eval's SCENARIO_CLEAN_DEGRADATION/
# SCENARIO_INJECTED_CURRENT_SPIKE, which stay held out for evaluation only
# (see module docstring's TRAINING/EVALUATION SCENARIO SEPARATION).
TRAINING_SCENARIOS: tuple[ScenarioConfig, ...] = (
    ScenarioConfig(
        name="training_a",
        seed=2001,
        length=60,
        start_health=1.0,
        end_health=0.2,
        degradation_rate=1.0,
        channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    ),
    ScenarioConfig(
        name="training_b",
        seed=2002,
        length=60,
        start_health=1.0,
        end_health=0.1,
        degradation_rate=1.5,
        channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.5)},
    ),
)

EVALUATION_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_CURRENT_SPIKE,
)


def _timestamps(n: int) -> list[str]:
    return [f"2026-08-10T00:{i // 60:02d}:{i % 60:02d}.000Z" for i in range(n)]


def _build_p2_pipeline() -> tuple[Preprocessor, P2Pipeline, ConsistencyProvider]:
    """A FRESH (preprocessor, pipeline, c_provider) triple per episode --
    same shared plumbing fixtures as edge/eval/rl_baseline_eval.py, reused
    by import rather than redefined with different values."""
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
        reward_weights=SIMULATION_REWARD_WEIGHTS_FIXTURE,  # required for training -- see docstring
    )


class _DQNNet(torch.nn.Module):
    """Single-hidden-layer MLP: STATE_WIDTH -> hidden_size -> len(RLAction)
    Q-values. ``hidden_size`` is REQUIRED, no default -- mirrors
    ``edge/models/lstm_twin.py``/``edge/models/lstm_prognosis.py``'s own
    convention."""

    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        self._net = torch.nn.Sequential(
            torch.nn.Linear(STATE_WIDTH, hidden_size),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden_size, len(ACTION_ORDER)),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self._net(x)


class DQNPolicy:
    """Implements ``edge.rl.policy.Policy`` (same Protocol
    ``BaselinePolicy`` does). Epsilon-greedy over the network's own
    Q-values. ALWAYS reports ``policy_validated=False`` and
    ``confidence=None`` (Q-values are not a calibrated probability -- see
    module docstring's POLICY VALIDATION section)."""

    def __init__(self, network: _DQNNet, *, epsilon: float, rng: random.Random) -> None:
        self._network = network
        self._epsilon = epsilon
        self._rng = rng

    def propose(self, state: RLState | None) -> PolicyDecision:
        if state is None:
            return self._decision(RLAction.safe_stop, "state is unavailable")

        if self._rng.random() < self._epsilon:
            action = self._rng.choice(ACTION_ORDER)
            return self._decision(action, f"epsilon-greedy exploration (epsilon={self._epsilon})")

        self._network.eval()
        with torch.no_grad():
            q_values = self._network(torch.tensor([state.to_vector()], dtype=torch.float32))
        action_index = int(torch.argmax(q_values[0]).item())
        return self._decision(ACTION_ORDER[action_index], "greedy argmax over Q-values")

    def _decision(self, action: RLAction, reason: str) -> PolicyDecision:
        return PolicyDecision(
            proposed_action=action,
            policy_available=True,
            policy_validated=False,
            confidence=None,
            policy_name=DQN_POLICY_NAME,
            policy_version=DQN_POLICY_VERSION,
            reason=reason,
        )


@dataclass(frozen=True)
class _Transition:
    state_vector: tuple[float, ...]
    action_index: int
    reward: float
    next_state_vector: tuple[float, ...]
    done: bool


class _ReplayBuffer:
    """A plain circular buffer + uniform random sampling. No dependency
    beyond the stdlib ``random.Random`` already used elsewhere in this
    module for determinism."""

    def __init__(self, capacity: int, rng: random.Random) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._rng = rng
        self._buffer: list[_Transition] = []
        self._position = 0

    def push(self, transition: _Transition) -> None:
        if len(self._buffer) < self._capacity:
            self._buffer.append(transition)
        else:
            self._buffer[self._position] = transition
            self._position = (self._position + 1) % self._capacity

    def sample(self, batch_size: int) -> list[_Transition]:
        return self._rng.sample(self._buffer, batch_size)

    def __len__(self) -> int:
        return len(self._buffer)


def _epsilon_for_episode(
    episode_index: int, epsilon_start: float, epsilon_end: float, decay_episodes: int
) -> float:
    """Linear decay -- the same "smallest, most defensible shape" argument
    already used for D020's own scaling-formula choice (no additional
    assumption about the rate of change beyond proportional-to-progress)."""
    if decay_episodes <= 0:
        return epsilon_end
    fraction = min(episode_index / decay_episodes, 1.0)
    return epsilon_start + (epsilon_end - epsilon_start) * fraction


def _dqn_update(
    policy_net: _DQNNet,
    target_net: _DQNNet,
    optimizer: torch.optim.Optimizer,
    batch: list[_Transition],
    gamma: float,
) -> float:
    states = torch.tensor([t.state_vector for t in batch], dtype=torch.float32)
    actions = torch.tensor([t.action_index for t in batch], dtype=torch.long)
    rewards = torch.tensor([t.reward for t in batch], dtype=torch.float32)
    next_states = torch.tensor([t.next_state_vector for t in batch], dtype=torch.float32)
    dones = torch.tensor([float(t.done) for t in batch], dtype=torch.float32)

    policy_net.train()
    q_values = policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)
    with torch.no_grad():
        next_q_values = target_net(next_states).max(dim=1).values
        targets = rewards + gamma * next_q_values * (1.0 - dones)
    loss = torch.nn.functional.mse_loss(q_values, targets)

    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return float(loss.item())


@dataclass(frozen=True)
class TrainingEpisodeRecord:
    """One training episode's summary -- deliberately similar in shape to
    ``edge.eval.rl_baseline_eval.EpisodeRecord`` for easy side-by-side
    comparison, with training-specific fields added."""

    episode_index: int
    scenario_name: str
    scenario_seed: int
    cumulative_reward: float
    step_count: int
    termination_cause: str  # "trajectory_exhausted" | "safe_stop"
    fallback_count: int
    fallback_rate: float
    requested_action_histogram: dict[str, int]
    approved_action_histogram: dict[str, int]
    final_health: float | None
    mean_training_loss: float | None
    epsilon_used: float
    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


@dataclass(frozen=True)
class TrainingRunResult:
    """One full training run's output. ``final_policy_net``/
    ``final_target_net`` are returned in-memory only -- no checkpoint is
    written to disk by this module (no checkpoint produced by this
    project's own tests/tooling is ever committed to the repo)."""

    episodes: tuple[TrainingEpisodeRecord, ...]
    loss_history: tuple[float, ...]
    hyperparameters: dict[str, object]
    final_policy_net: _DQNNet = field(repr=False)
    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def train_dqn(
    *,
    training_scenarios: Sequence[ScenarioConfig],
    hidden_size: int,
    episodes: int,
    gamma: float,
    learning_rate: float,
    epsilon_start: float,
    epsilon_end: float,
    epsilon_decay_episodes: int,
    replay_capacity: int,
    batch_size: int,
    target_update_interval: int,
    seed: int,
) -> TrainingRunResult:
    """Run ``episodes`` of DQN training, cycling through
    ``training_scenarios``. Every argument is REQUIRED -- no default
    anywhere in this function (see module docstring). Raises ``ValueError``
    if any transition's reward total is ``None`` (see module docstring's
    REWARD HANDLING section) -- this indicates a misconfigured environment,
    not a condition to route around silently.

    Hardware-free plumbing verification ONLY: proves the training loop
    runs, loss is finite, and the policy's action distribution changes
    over episodes on SYNTHETIC data. Establishes NO real-world accuracy,
    safety, or validation claim whatsoever -- see module docstring.
    """
    if not training_scenarios:
        raise ValueError("training_scenarios must not be empty")

    rng = random.Random(seed)
    torch.manual_seed(seed)
    policy_net = _DQNNet(hidden_size=hidden_size)
    target_net = _DQNNet(hidden_size=hidden_size)
    target_net.load_state_dict(policy_net.state_dict())
    optimizer = torch.optim.Adam(policy_net.parameters(), lr=learning_rate)
    replay = _ReplayBuffer(capacity=replay_capacity, rng=rng)

    episode_records: list[TrainingEpisodeRecord] = []
    loss_history: list[float] = []

    for episode_index in range(episodes):
        scenario = training_scenarios[episode_index % len(training_scenarios)]
        epsilon = _epsilon_for_episode(
            episode_index, epsilon_start, epsilon_end, epsilon_decay_episodes
        )
        env = _build_environment(scenario)
        policy = DQNPolicy(policy_net, epsilon=epsilon, rng=rng)

        state = env.reset()
        done = False
        episode_losses: list[float] = []
        fallback_count = 0
        requested_histogram: Counter[str] = Counter()
        approved_histogram: Counter[str] = Counter()
        cumulative_reward = 0.0
        step_count = 0
        last_info: dict[str, object] = {}

        while not done:
            decision = policy.propose(state)
            result = env.step(
                decision.proposed_action,
                policy_available=decision.policy_available,
                policy_validated=decision.policy_validated,
                confidence=decision.confidence,
            )

            reward_total = result.reward.total
            if reward_total is None:
                raise ValueError(
                    "train_dqn() requires a weighted RewardResult (total is not None) -- "
                    "the environment must be constructed with reward_weights= an explicit "
                    "RewardWeights; got total=None, which train_dqn() never silently handles"
                )

            replay.push(
                _Transition(
                    state_vector=state.to_vector(),
                    action_index=ACTION_ORDER.index(decision.proposed_action),
                    reward=reward_total,
                    next_state_vector=result.state.to_vector(),
                    done=result.done,
                )
            )

            if len(replay) >= batch_size:
                batch = replay.sample(batch_size)
                loss = _dqn_update(policy_net, target_net, optimizer, batch, gamma)
                loss_history.append(loss)
                episode_losses.append(loss)

            cumulative_reward += reward_total
            step_count += 1
            fallback_count += int(result.gate_decision.fallback_used)
            requested_histogram[result.gate_decision.requested_action.value] += 1
            approved_histogram[result.gate_decision.approved_action.value] += 1
            last_info = result.info
            state = result.state
            done = result.done

        if (episode_index + 1) % target_update_interval == 0:
            target_net.load_state_dict(policy_net.state_dict())

        termination_cause = (
            "trajectory_exhausted" if last_info.get("trajectory_exhausted") else "safe_stop"
        )
        episode_records.append(
            TrainingEpisodeRecord(
                episode_index=episode_index,
                scenario_name=scenario.name,
                scenario_seed=scenario.seed,
                cumulative_reward=cumulative_reward,
                step_count=step_count,
                termination_cause=termination_cause,
                fallback_count=fallback_count,
                fallback_rate=(fallback_count / step_count) if step_count else 0.0,
                requested_action_histogram=dict(requested_histogram),
                approved_action_histogram=dict(approved_histogram),
                final_health=state.health,
                mean_training_loss=(
                    sum(episode_losses) / len(episode_losses) if episode_losses else None
                ),
                epsilon_used=epsilon,
            )
        )

    hyperparameters = {
        "hidden_size": hidden_size,
        "episodes": episodes,
        "gamma": gamma,
        "learning_rate": learning_rate,
        "epsilon_start": epsilon_start,
        "epsilon_end": epsilon_end,
        "epsilon_decay_episodes": epsilon_decay_episodes,
        "replay_capacity": replay_capacity,
        "batch_size": batch_size,
        "target_update_interval": target_update_interval,
        "seed": seed,
    }
    return TrainingRunResult(
        episodes=tuple(episode_records),
        loss_history=tuple(loss_history),
        hyperparameters=hyperparameters,
        final_policy_net=policy_net,
    )


def evaluate_greedy(network: _DQNNet, scenario: ScenarioConfig) -> TrainingEpisodeRecord:
    """Run one fully-greedy (epsilon=0) episode of ``network`` against
    ``scenario`` -- for comparing a trained network against the baselines
    on a HELD-OUT scenario (see module docstring). No exploration, no
    training update -- diagnostic evaluation only."""
    rng = random.Random(0)  # only used if state is ever None; greedy path never draws from it
    env = _build_environment(scenario)
    policy = DQNPolicy(network, epsilon=0.0, rng=rng)

    state = env.reset()
    done = False
    fallback_count = 0
    requested_histogram: Counter[str] = Counter()
    approved_histogram: Counter[str] = Counter()
    cumulative_reward = 0.0
    step_count = 0
    last_info: dict[str, object] = {}

    while not done:
        decision = policy.propose(state)
        result = env.step(
            decision.proposed_action,
            policy_available=decision.policy_available,
            policy_validated=decision.policy_validated,
            confidence=decision.confidence,
        )
        reward_total = result.reward.total
        if reward_total is None:
            raise ValueError("evaluate_greedy() requires a weighted RewardResult; got total=None")
        cumulative_reward += reward_total
        step_count += 1
        fallback_count += int(result.gate_decision.fallback_used)
        requested_histogram[result.gate_decision.requested_action.value] += 1
        approved_histogram[result.gate_decision.approved_action.value] += 1
        last_info = result.info
        state = result.state
        done = result.done

    termination_cause = (
        "trajectory_exhausted" if last_info.get("trajectory_exhausted") else "safe_stop"
    )
    return TrainingEpisodeRecord(
        episode_index=-1,
        scenario_name=scenario.name,
        scenario_seed=scenario.seed,
        cumulative_reward=cumulative_reward,
        step_count=step_count,
        termination_cause=termination_cause,
        fallback_count=fallback_count,
        fallback_rate=(fallback_count / step_count) if step_count else 0.0,
        requested_action_histogram=dict(requested_histogram),
        approved_action_histogram=dict(approved_histogram),
        final_health=state.health,
        mean_training_loss=None,
        epsilon_used=0.0,
    )


def main() -> None:
    """Diagnostic entry point: ``python -m edge.eval.rl_training``. Trains
    a tiny DQN on ``TRAINING_SCENARIOS``, then evaluates it greedily on
    the HELD-OUT ``EVALUATION_SCENARIOS`` alongside ``BaselinePolicy`` and
    the pure-fallback baseline. NOT an accuracy or validation claim -- see
    module docstring."""
    result = train_dqn(
        training_scenarios=TRAINING_SCENARIOS,
        hidden_size=HIDDEN_SIZE_FIXTURE,
        episodes=TRAIN_EPISODES_FIXTURE,
        gamma=GAMMA_FIXTURE,
        learning_rate=LEARNING_RATE_FIXTURE,
        epsilon_start=EPSILON_START_FIXTURE,
        epsilon_end=EPSILON_END_FIXTURE,
        epsilon_decay_episodes=EPSILON_DECAY_EPISODES_FIXTURE,
        replay_capacity=REPLAY_BUFFER_SIZE_FIXTURE,
        batch_size=BATCH_SIZE_FIXTURE,
        target_update_interval=TARGET_UPDATE_INTERVAL_FIXTURE,
        seed=SEED_FIXTURE,
    )

    print("=== DQN training harness (diagnostic, simulation-only) ===")
    for ep in result.episodes:
        print(
            f"episode {ep.episode_index:03d} [{ep.scenario_name}] "
            f"reward={ep.cumulative_reward:.3f} steps={ep.step_count} "
            f"fallback_rate={ep.fallback_rate:.2f} epsilon={ep.epsilon_used:.3f} "
            f"loss={ep.mean_training_loss}"
        )

    print("\n=== Held-out evaluation (greedy DQN vs. existing baselines) ===")
    for scenario in EVALUATION_SCENARIOS:
        dqn_record = evaluate_greedy(result.final_policy_net, scenario)
        baseline_record = run_baseline_policy_episode(scenario)
        fallback_record = run_pure_fallback_episode(scenario)
        print(f"[{scenario.name}]")
        print(
            f"  dqn(greedy):     reward={dqn_record.cumulative_reward:.3f} "
            f"fallback_rate={dqn_record.fallback_rate:.2f}"
        )
        print(
            f"  baseline_policy: reward={baseline_record.cumulative_reward:.3f} "
            f"fallback_rate={baseline_record.fallback_rate:.2f}"
        )
        print(
            f"  pure_fallback:   reward={fallback_record.cumulative_reward:.3f} "
            f"fallback_rate={fallback_record.fallback_rate:.2f}"
        )

    print(
        "\nNOTE: this only proves the DQN training loop's PLUMBING works "
        "(forward/backward pass, replay buffer, target-network updates, "
        "epsilon decay) on SYNTHETIC data. It does NOT establish real-world "
        "accuracy, safety, or a validated policy (model_status="
        "diagnostic_unvalidated) -- see module docstring."
    )


if __name__ == "__main__":
    main()
