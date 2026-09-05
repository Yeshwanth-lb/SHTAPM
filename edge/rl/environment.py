"""Simulation-only RL environment (FR-RL1/RL2/RL3/RL4 scaffolding) -- state,
transition, safety-gating, and reward mechanics. No policy, no training
loop exists yet.

data_source=synthetic · execution_mode=simulation · model_status=diagnostic_unvalidated

REUSE, NOT DUPLICATION: this module builds no new anomaly/trust/attribution
logic, no new prognosis inference, no new isolation policy, and no new
safety-gating or reward logic -- every one of those already exists
elsewhere and is wired together, unmodified, here:
  - ``edge.models.degradation_generator.SyntheticDegradationGenerator``
    (gradual wear-out telemetry -- ground-truth, NOT a model inference;
    see ``_build_state()``)
  - ``edge.injection.injections`` (discrete faults/attacks layered on top,
    applied once over the whole generated stream at construction time,
    exactly as ``edge/eval/if_eval.py``/``swat_eval.py`` already do)
  - ``edge.pipeline.monitor.LiveP2Monitor`` (the SAME warm-up/sliding-window
    P2 wiring ``edge/main.py`` uses for the live path -- not reimplemented)
  - ``edge.pipeline.isolation_tracker.IsolationFallbackTracker`` (persistent,
    per-episode isolation-candidate tracking -- feeds the fallback gate;
    NOT called directly for actuation)
  - ``edge.pipeline.prognosis_runtime.PrognosisRuntime`` (optional; if
    omitted, every state's ``failure_eta`` is honestly ``None``)
  - ``edge.rl.state.build_rl_state`` (FR-RL1's state vector, unmodified)
  - ``edge.rl.fallback_gate.evaluate_rl_action`` (FR-RL4's safety gate,
    unmodified -- see STEP CONTRACT below)
  - ``edge.rl.reward.compute_reward`` (FR-RL3's reward shape, unmodified --
    see REWARD WIRING below)

ACTION REPRESENTATION: exactly the existing, already-approved
``app.schemas.contracts.RLAction`` enum (FR-RL2 / Doc05
``decisions.rl_action``). ``step(action, ...)`` still takes the requested
action directly as its first positional argument -- unchanged from the
prior version -- satisfying "obtain the requested action from ... step
input"; nothing in this module holds an internal ``Policy`` reference (a
caller, e.g. a future training loop, is expected to call
``Policy.propose(state)`` itself and pass the resulting action in).

STEP CONTRACT (this increment's core change): each ``step(action, ...)``
call now:
  1. captures ``previous_state`` (the state as of the last ``reset()``/
     ``step()`` call, BEFORE this tick's transition);
  2. updates the persistent ``IsolationFallbackTracker`` from the outcome
     that produced ``previous_state`` (exactly the outcome ``previous_
     state`` was itself built from -- temporally consistent);
  3. calls ``evaluate_rl_action()`` with the REQUESTED ``action`` and
     ``previous_state`` -- the gate is ALWAYS consulted, for every action,
     valid or not; this module never second-guesses or bypasses it, and
     never raises for an invalid/unrecognized action itself (that is
     exactly the gate's job -- see the CORRECTION note below);
  4. applies the already-defined simulation transition (advances one
     buffered frame through the same real, unmodified P2 pipeline);
  5. captures ``next_state``;
  6. calls ``compute_reward(previous_state, gate_decision, next_state,
     weights=self._reward_weights)`` -- ``weights`` is ``None`` (the
     reward module's UNWEIGHTED mode) unless the constructor was given an
     explicit ``reward_weights``;
  7. returns an ``EnvironmentStepResult`` carrying ``state`` (next),
     ``reward`` (a real ``RewardResult``, not a placeholder),
     ``gate_decision`` (the full ``GateDecision``, so requested/approved/
     fallback-used/safety-status are never conflated with each other or
     with the reward), ``done``, and diagnostic ``info``.

CORRECTION FROM THE PRIOR VERSION: ``step()`` used to raise ``ValueError``
itself for a non-``RLAction`` input, handling invalid actions locally
instead of through the gate. That was exactly the kind of bypass this
increment's own safety requirement forbids ("the environment must never
bypass the fallback gate") -- an invalid/unrecognized action is now passed
straight into ``evaluate_rl_action()``, which already safely falls back
for it (proven in ``edge/tests/test_rl_fallback_gate.py``); ``step()``
itself never raises for a bad action value anymore, only for genuine
misuse (calling it before ``reset()`` or after termination).

TERMINATION is decided from ``gate_decision.approved_action`` (what the
gate actually let happen), never the raw ``requested_action`` -- another
direct consequence of "the environment must never bypass the fallback
gate": if a request were ever overridden away from ``safe_stop`` (it
cannot be, per the gate's own carve-out) or forced INTO ``safe_stop`` by
the gate's hard safety rules, termination must follow what was actually
approved, not what was merely asked for.

POLICY VALIDATION IS NEVER GRANTED HERE: ``step()``'s ``policy_available``/
``policy_validated``/``confidence`` keyword arguments are passed straight
through to the gate with conservative defaults
(``policy_available=True, policy_validated=False``) -- this module
introduces no logic that could ever flip ``policy_validated`` to ``True``
on its own; that determination belongs entirely to whatever supplies the
action (a ``Policy`` implementation, or a test).

ALREADY-ACTIVE SAFE-STOP: this environment's ``already_safe_stopped``
value passed to the gate is always ``False``. This is honest, not an
oversight: an episode already TERMINATES the same step ``safe_stop`` is
approved (``step()`` raises on any further call), so there is no
subsequent tick in which the system is "already" safe-stopped for this
environment to report -- that condition only becomes meaningful once a
composition root persists state across multiple ticks/episodes, which
does not exist yet.

REWARD WIRING: reward is computed from ``gate_decision.requested_action``
(what the policy wanted), not ``approved_action`` -- see
``edge/rl/reward.py``'s own module docstring for why (safety-shielding:
rewarding only the gate-approved outcome would teach a policy to request
anything and lean on the gate). No research weight is introduced by this
module -- ``reward_weights`` defaults to ``None`` (unweighted mode);
passing ``edge.rl.reward.SIMULATION_REWARD_WEIGHTS_FIXTURE`` (or any other
explicit ``RewardWeights``) is the caller's choice, never this module's
default.

GROUND TRUTH VS. INFERENCE: ``_build_state()``'s ``health`` value comes
from the synthetic degradation generator's own continuous ground truth
(``self._health[raw.sample_seq]``), NEVER from a trained model -- this was
true before this increment and is unchanged by it. ``failure_eta`` (when a
``PrognosisRuntime`` is supplied) DOES come from a real model inference.
Nothing in this module blends or relabels the two.

SAFETY BOUNDARY (unchanged): this module performs NO actuation. It never
invokes the P2-to-P3 self-healing adapter or orchestrator
(``edge/pipeline/cycle.py``, ``edge/pipeline/self_heal.py``), any actuator
or general-purpose I/O pin, or any network/decision-publishing code, and
never will inside this module.

EPISODE CONTRACT (unchanged from the prior version):
  - The full telemetry trajectory (degradation + injections) is generated
    ONCE at construction, from the caller-supplied, already-seeded
    ``generator``/``injections`` -- fully deterministic given that config.
  - ``reset()`` may be called ONLY ONCE per environment instance. P2's own
    ``ConsistencyProvider``/``LiveP2Monitor`` are stateful and fit-once by
    design -- there is no supported way to "rewind" that state safely. A
    second ``reset()`` call raises ``RuntimeError``; construct a new
    environment instance (with a fresh ``pipeline``/``c_provider`` pair)
    for a new episode.
  - An episode terminates when either the trajectory's frames are
    exhausted, or the gate's ``approved_action`` is ``RLAction.safe_stop``.

PUBLIC CONTRACT CHANGES (see the increment's own report for full detail):
  - Constructor gains one new REQUIRED keyword argument,
    ``confidence_threshold`` (no default, mirrors
    ``evaluate_rl_action()``'s own requirement), and one new OPTIONAL
    argument, ``reward_weights`` (default ``None``).
  - ``step()`` gains three new OPTIONAL keyword arguments
    (``policy_available``, ``policy_validated``, ``confidence``) --
    existing positional call sites (``env.step(action)``) are unaffected.
  - ``step()`` no longer raises ``ValueError`` for an invalid action (see
    CORRECTION note above).
  - ``EnvironmentStepResult.reward`` is now a real
    ``edge.rl.reward.RewardResult`` instead of the old placeholder
    ``RewardSignal`` (removed -- it served no purpose once real reward
    wiring existed).
  - ``EnvironmentStepResult`` gains a new ``gate_decision`` field.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.schemas.contracts import RLAction

from edge.anomaly.pipeline import P2Pipeline, WindowOutcome
from edge.anomaly.preprocess import Preprocessor
from edge.injection.injections import Injection
from edge.models.degradation_generator import SyntheticDegradationGenerator
from edge.pipeline.isolation_tracker import IsolationFallbackTracker
from edge.pipeline.monitor import LiveP2Monitor, RawChannelValues
from edge.rl.fallback_gate import GateDecision, evaluate_rl_action
from edge.rl.reward import RewardResult, RewardWeights, compute_reward
from edge.rl.state import RLState, build_rl_state
from edge.trust.c_consistency import ConsistencyProvider

if TYPE_CHECKING:  # pragma: no cover - import-time-only, avoids a hard torch
    # dependency for callers that never pass a real PrognosisRuntime (see
    # module docstring; edge.pipeline.prognosis_runtime imports torch
    # transitively via edge.models.lstm_prognosis).
    from edge.pipeline.prognosis_runtime import PrognosisRuntime

EXECUTION_MODE = "simulation"
DATA_SOURCE = "synthetic"
MODEL_STATUS = "diagnostic_unvalidated"


@dataclass(frozen=True)
class EnvironmentStepResult:
    state: RLState
    reward: RewardResult
    done: bool
    info: dict[str, object]
    gate_decision: GateDecision


class SHTAPMSimulationEnvironment:
    """One deterministic, single-use simulation episode -- see module
    docstring's EPISODE CONTRACT."""

    def __init__(
        self,
        *,
        generator: SyntheticDegradationGenerator,
        timestamps: list[str],
        preprocessor: Preprocessor,
        pipeline: P2Pipeline,
        c_provider: ConsistencyProvider,
        fit_window_count: int,
        confidence_threshold: float,
        injections: Sequence[Injection] = (),
        prognosis_runtime: PrognosisRuntime | None = None,
        reward_weights: RewardWeights | None = None,
    ) -> None:
        trajectory = generator.generate(timestamps)
        frames = list(trajectory.frames)
        for injection in injections:
            frames = injection.apply(frames).frames
        self._frames = frames
        self._health = trajectory.health  # ground truth is unaffected by injections (see docstring)

        fit_buffer_size = preprocessor.window_size + (fit_window_count - 1) * preprocessor.step
        if len(self._frames) <= fit_buffer_size:
            raise ValueError(
                f"trajectory length ({len(self._frames)}) must exceed the P2 fit buffer size "
                f"({fit_buffer_size}) so at least one real step is possible"
            )

        self._latest_outcome: WindowOutcome | None = None
        self._latest_raw: RawChannelValues | None = None
        self._monitor = LiveP2Monitor(
            preprocessor=preprocessor,
            pipeline=pipeline,
            c_provider=c_provider,
            fit_window_count=fit_window_count,
            on_outcome=self._capture_outcome,
            on_raw_values=self._capture_raw,
        )
        self._prognosis_runtime = prognosis_runtime
        self._isolation_tracker = IsolationFallbackTracker()
        self._confidence_threshold = confidence_threshold
        self._reward_weights = reward_weights

        self._cursor = 0
        self._has_reset = False
        self._done = False
        self._last_state: RLState | None = None

    def _capture_outcome(self, outcome: WindowOutcome) -> None:
        self._latest_outcome = outcome

    def _capture_raw(self, _outcome: WindowOutcome, raw: RawChannelValues) -> None:
        self._latest_raw = raw

    def _feed_next_frame(self) -> None:
        if self._cursor >= len(self._frames):
            raise RuntimeError("no more frames in this episode's trajectory")
        frame = self._frames[self._cursor]
        self._cursor += 1
        self._monitor.on_frame(frame)

    def reset(self) -> RLState:
        """Feed frames until the first real ``WindowOutcome`` exists (P2's
        warm-up), then return the initial ``RLState``. May be called ONLY
        ONCE per instance -- see module docstring's EPISODE CONTRACT.

        Raises:
            RuntimeError: if called more than once.
        """
        if self._has_reset:
            raise RuntimeError(
                "reset() may only be called once per environment instance "
                "(P2's ConsistencyProvider/LiveP2Monitor are stateful, fit-"
                "once components with no supported rewind) -- construct a "
                "new SHTAPMSimulationEnvironment for a new episode; see "
                "module docstring's EPISODE CONTRACT"
            )
        self._has_reset = True
        while self._latest_outcome is None:
            self._feed_next_frame()
        initial_state = self._build_state()
        self._last_state = initial_state
        return initial_state

    def step(
        self,
        action: RLAction,
        *,
        policy_available: bool = True,
        policy_validated: bool = False,
        confidence: float | None = None,
    ) -> EnvironmentStepResult:
        """Advance one tick through the full gate/transition/reward
        pipeline -- see module docstring's STEP CONTRACT. Never performs
        actuation, isolation, or self-healing (see SAFETY BOUNDARY).

        ``policy_available``/``policy_validated``/``confidence`` describe
        whatever produced ``action`` (typically an
        ``edge.rl.policy.PolicyDecision``'s own fields) -- this method
        never infers or upgrades them; ``policy_validated`` defaults to
        ``False`` (never assume validation -- see module docstring).

        Raises:
            RuntimeError: if called before ``reset()``, or after the
                episode has already terminated. Never raises for an
                invalid/unrecognized ``action`` -- see module docstring's
                CORRECTION note; the fallback gate handles that safely.
        """
        if not self._has_reset:
            raise RuntimeError("step() called before reset()")
        if self._done:
            raise RuntimeError(
                "step() called after episode termination; construct a new environment"
            )

        previous_state = self._last_state
        assert previous_state is not None  # guaranteed once reset() has run
        assert self._latest_outcome is not None  # same guarantee

        isolation_status = self._isolation_tracker.update(self._latest_outcome)
        gate_decision = evaluate_rl_action(
            requested_action=action,
            state=previous_state,
            isolation_status=isolation_status,
            policy_available=policy_available,
            policy_validated=policy_validated,
            confidence_threshold=self._confidence_threshold,
            confidence=confidence,
            already_safe_stopped=False,  # see module docstring
        )

        self._feed_next_frame()  # the already-defined simulation transition
        next_state = self._build_state()

        reward = compute_reward(
            previous_state=previous_state,
            gate_decision=gate_decision,
            next_state=next_state,
            weights=self._reward_weights,
        )

        exhausted = self._cursor >= len(self._frames)
        done = exhausted or gate_decision.approved_action is RLAction.safe_stop
        self._done = done
        self._last_state = next_state

        requested_value = (
            gate_decision.requested_action.value
            if isinstance(gate_decision.requested_action, RLAction)
            else gate_decision.requested_action
        )
        info: dict[str, object] = {
            "execution_mode": EXECUTION_MODE,
            "data_source": DATA_SOURCE,
            "model_status": MODEL_STATUS,
            "requested_action": requested_value,
            "approved_action": gate_decision.approved_action.value,
            "fallback_used": gate_decision.fallback_used,
            "fallback_reason": gate_decision.fallback_reason,
            "safety_status": gate_decision.safety_status,
            "deterministic_fallback_would_isolate": sorted(isolation_status.candidates_this_cycle),
            "persistent_isolation_tracked_channels": sorted(isolation_status.tracked_channels),
            "trajectory_exhausted": exhausted,
        }
        return EnvironmentStepResult(
            state=next_state, reward=reward, done=done, info=info, gate_decision=gate_decision
        )

    def _build_state(self) -> RLState:
        outcome = self._latest_outcome
        raw = self._latest_raw
        assert outcome is not None and raw is not None  # guaranteed once reset() has run

        health = self._health[raw.sample_seq]  # ground truth -- see module docstring

        failure_eta: float | None = None
        prognosis_data_source: str | None = None
        health_label_source: str | None = None
        if self._prognosis_runtime is not None:
            result = self._prognosis_runtime.predict(outcome.window, outcome.trust)
            failure_eta = result.failure_eta
            prognosis_data_source = result.prognosis_data_source
            health_label_source = result.health_label_source

        return build_rl_state(
            health=health,
            anomaly_flag=outcome.anomaly.flag,
            trust=outcome.trust,
            failure_eta=failure_eta,
            execution_mode=EXECUTION_MODE,
            prognosis_data_source=prognosis_data_source,
            health_label_source=health_label_source,
        )
