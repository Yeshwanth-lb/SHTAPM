"""U06 DQN-policy diagnostic evaluation -- pure, additive, opt-in,
TORCH-DEPENDENT (via ``edge.eval.rl_training``, unmodified). Trains one
DQN policy under a fixed, documented diagnostic configuration, evaluates
it greedily against the complete evaluation-scenario taxonomy, and runs
all four existing U06 summaries over the resulting ``EpisodeRecord``s.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

METHODOLOGY -- HUMAN-APPROVED, NOT THIS MODULE'S OWN CHOICE: the exact
training configuration below (reward fixture, hyperparameters, seed) was
explicitly approved by the U06 decision owner (see ``project-state/
DECISIONS.md``'s "U06 -- DQN Diagnostic Evaluation Methodology Decision"
record). This module implements that configuration verbatim -- it does
not choose, tune, or recommend any configuration of its own.

SCOPE -- DIAGNOSTIC ONLY, NO REWARD-WEIGHT DECISION, NO ACCEPTANCE
CRITERION: ``SIMULATION_REWARD_WEIGHTS_FIXTURE`` is used here ONLY as a
fixed, already-existing, already-used-elsewhere diagnostic fixture -- its
use here is NOT, and must never be read as, an approved U06 reward-weight
decision (see the "U06 -- RL REWARD SHAPING SPECIFICATION PROPOSAL"
section's own §8, still unsatisfied). This module chooses no acceptable
rate, threshold, or verdict for the resulting numbers, and compares the
DQN policy against no invented acceptance criterion of any kind.

INTEGRATION -- REUSES, NEVER REWRITES: this module calls
``edge.eval.rl_training.train_dqn()`` and ``DQNPolicy`` completely
unmodified, and calls ``edge.eval.rl_baseline_eval.run_dqn_policy_episode()``
(a generic, torch-free runner added specifically to support this use case)
completely unmodified. It never edits any existing axis/comparison module
(``edge.eval.u06_rate_summary``, ``edge.eval.u06_tracker_agreement``,
``edge.eval.u06_ground_truth_rate_summary``, ``edge.eval.
u06_channel_agreement``) -- it only calls their already-committed
``summarize_*`` functions, exactly as the aggregate diagnostic report and
every seed-repetition report already do for the two deterministic
baselines.

DEDICATED SEED, NOT SILENTLY REUSED: ``edge.eval.rl_training.SEED_FIXTURE``
(``1337``) collides with ``edge.eval.rl_baseline_eval.
SCENARIO_CLEAN_DEGRADATION``'s own seed -- reusing it here without comment
would conflate a training-run RNG seed with an evaluation-scenario seed.
This module instead defines and documents its own dedicated
``U06_DQN_DIAGNOSTIC_SEED`` (see below), used for both ``train_dqn()``'s
``seed=`` argument and the greedy-evaluation policy's own (unused, since
``epsilon=0.0`` never draws from it) RNG.

FRESH TRAINING, NO CHECKPOINT PERSISTENCE: ``build_dqn_diagnostic_report()``
trains a brand-new network in memory on every call -- exactly matching
``edge.eval.rl_training.TrainingRunResult``'s own "no checkpoint is written
to disk by this module" convention. No new persistence mechanism (file,
database, or otherwise) is introduced anywhere in this module.

GREEDY EVALUATION, NOT EXPLORATION: evaluation uses ``epsilon=0.0`` (pure
greedy argmax over the trained network's Q-values) -- matching
``edge.eval.rl_training.evaluate_greedy()``'s own established convention
for "compare a trained network against the baselines" use, as distinct
from the epsilon-greedy exploration `train_dqn()` itself uses internally
during training.

NO THRESHOLD, NO VERDICT, NO REAL-WORLD CLAIM: this module produces no
pass/fail judgment, no acceptable-rate determination, and no accuracy,
safety, effectiveness, validation, or production-readiness claim of any
kind, for any scenario or axis. Every number any of the four wrapped
summary functions produces retains whatever disclaimers that function's
own module docstring already attaches to it. U06 (``project-state/
DECISIONS.md``) remains fully open -- nothing here resolves or partially
resolves it. This diagnostic result additionally inherits the same
world-inert-environment ceiling every other U06 evaluation already has
(see the "U06 -- RL REWARD SHAPING SPECIFICATION PROPOSAL" section's own
§9): ``continue_``/``alert``/``reduce_weight`` have no trajectory effect
regardless of which policy requests them, so this evaluation can only
measure whether this policy's own requested-action bookkeeping is
internally consistent on synthetic data -- never real fault-detection
consequences.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from edge.eval.rl_baseline_eval import (
    INJECTION_TYPE_SCENARIOS,
    SCENARIO_CLEAN_DEGRADATION,
    ScenarioConfig,
    run_dqn_policy_episode,
)
from edge.eval.rl_training import (
    BATCH_SIZE_FIXTURE,
    EPSILON_DECAY_EPISODES_FIXTURE,
    EPSILON_END_FIXTURE,
    EPSILON_START_FIXTURE,
    GAMMA_FIXTURE,
    HIDDEN_SIZE_FIXTURE,
    LEARNING_RATE_FIXTURE,
    REPLAY_BUFFER_SIZE_FIXTURE,
    TARGET_UPDATE_INTERVAL_FIXTURE,
    TRAIN_EPISODES_FIXTURE,
    TRAINING_SCENARIOS,
    DQNPolicy,
    train_dqn,
)
from edge.eval.u06_channel_agreement import (
    ChannelAgreementSummary,
    summarize_channel_agreement,
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
from edge.rl.reward import SIMULATION_REWARD_WEIGHTS_FIXTURE

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"

REWARD_WEIGHTS_FIXTURE_NAME = "SIMULATION_REWARD_WEIGHTS_FIXTURE"

# Dedicated U06 diagnostic-evaluation seed -- deliberately distinct from
# edge.eval.rl_training.SEED_FIXTURE (1337), which collides with
# edge.eval.rl_baseline_eval.SCENARIO_CLEAN_DEGRADATION's own seed (see
# module docstring's DEDICATED SEED section). Not reused from, or
# colliding with, any other seed in this codebase (verified directly
# against every evaluation-scenario, seed-repetition-variant, and
# training-scenario seed already committed).
U06_DQN_DIAGNOSTIC_SEED = 5001

_EVALUATION_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_CLEAN_DEGRADATION,
    *INJECTION_TYPE_SCENARIOS,
)


@dataclass(frozen=True)
class DQNScenarioResult:
    """One evaluation scenario's independent axis (i)/(ii)/(iii) and
    channel-agreement summaries for the greedy-evaluated DQN policy -- see
    module docstring. Never combined with any other result."""

    scenario_name: str
    baseline_name: str
    episode_rate_summary: EpisodeRateSummary
    tracker_agreement_summary: TrackerAgreementSummary
    ground_truth_rate_summary: GroundTruthRateSummary
    channel_agreement_summary: ChannelAgreementSummary

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


@dataclass(frozen=True)
class DQNDiagnosticReport:
    """The complete, scenario-separated DQN diagnostic report -- see
    module docstring. ``results`` is a flat, ordered tuple of
    ``DQNScenarioResult``s, one per evaluation scenario; it is NOT a
    pooled or averaged summary -- no such summary exists anywhere in this
    module. ``diagnostic_seed``/``reward_weights_fixture_name`` document
    exactly which fixed configuration produced this report -- see module
    docstring's METHODOLOGY section; neither is a U06 decision."""

    results: tuple[DQNScenarioResult, ...]
    diagnostic_seed: int
    reward_weights_fixture_name: str

    execution_mode: str = EXECUTION_MODE
    data_source: str = DATA_SOURCE
    model_status: str = MODEL_STATUS


def _adapt_dqn_policy_to_propose_fn(policy: DQNPolicy):
    """Adapt ``DQNPolicy.propose()`` (returning a ``PolicyDecision``) into
    the exact ``_ProposeFn`` shape ``run_dqn_policy_episode()`` requires --
    mirroring ``edge.eval.rl_baseline_eval.run_baseline_policy_episode``'s
    own identical adapter shape for ``BaselinePolicy``."""

    def _propose(state):
        decision = policy.propose(state)
        return (
            decision.proposed_action,
            decision.policy_available,
            decision.policy_validated,
            decision.confidence,
        )

    return _propose


def build_dqn_diagnostic_report() -> DQNDiagnosticReport:
    """Train one DQN policy under the fixed, documented diagnostic
    configuration (see module docstring), evaluate it greedily
    (``epsilon=0.0``) against the complete evaluation-scenario taxonomy,
    and run all four existing U06 summaries over each resulting
    ``EpisodeRecord``. Fresh, in-memory training on every call -- no
    checkpoint is read or written. Takes no parameters; always returns
    exactly ``len(_EVALUATION_SCENARIOS)`` results.
    """
    training_result = train_dqn(
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
        seed=U06_DQN_DIAGNOSTIC_SEED,
        reward_weights=SIMULATION_REWARD_WEIGHTS_FIXTURE,
    )

    greedy_policy = DQNPolicy(
        training_result.final_policy_net,
        epsilon=0.0,
        rng=random.Random(U06_DQN_DIAGNOSTIC_SEED),
    )
    propose_action = _adapt_dqn_policy_to_propose_fn(greedy_policy)

    results: list[DQNScenarioResult] = []
    for scenario in _EVALUATION_SCENARIOS:
        record = run_dqn_policy_episode(
            scenario,
            propose_action,
            reward_weights=SIMULATION_REWARD_WEIGHTS_FIXTURE,
        )
        results.append(
            DQNScenarioResult(
                scenario_name=record.scenario_name,
                baseline_name=record.baseline_name,
                episode_rate_summary=summarize_episode_rates(record),
                tracker_agreement_summary=summarize_tracker_agreement(record),
                ground_truth_rate_summary=summarize_ground_truth_rates(record),
                channel_agreement_summary=summarize_channel_agreement(record),
            )
        )

    return DQNDiagnosticReport(
        results=tuple(results),
        diagnostic_seed=U06_DQN_DIAGNOSTIC_SEED,
        reward_weights_fixture_name=REWARD_WEIGHTS_FIXTURE_NAME,
    )


def main() -> None:
    """Diagnostic entry point:
    ``python -m edge.eval.u06_dqn_evaluation_report``. Trains one DQN
    policy under the fixed diagnostic configuration and prints a concise,
    scenario-separated summary. NOT a validation claim, NOT a pass/fail
    judgment, NOT a reward-weight decision -- see module docstring."""
    print("=== U06 DQN-policy diagnostic evaluation (simulation-only) ===")
    print(
        f"Fixed diagnostic configuration: seed={U06_DQN_DIAGNOSTIC_SEED}, "
        f"reward_weights={REWARD_WEIGHTS_FIXTURE_NAME} "
        "(a fixed diagnostic fixture, NOT an approved U06 reward-weight decision)"
    )
    report = build_dqn_diagnostic_report()
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
    print(
        "NOTE: every number above is diagnostic, simulation-only, and "
        "scenario-specific (data_source=synthetic, execution_mode=simulation, "
        "model_status=diagnostic_unvalidated). No number here is pooled across "
        "scenarios, is a threshold, is a verdict, or is a real-world accuracy, "
        "safety, effectiveness, validation, or production-readiness claim. The "
        "reward fixture used is a fixed diagnostic fixture only, not an "
        "approved U06 reward-weight decision."
    )


if __name__ == "__main__":
    main()
