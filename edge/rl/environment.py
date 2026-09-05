"""Simulation-only RL environment (FR-RL1/RL2 scaffolding) -- state and
transition mechanics ONLY. No policy, no training loop, no reward weights,
no composition-root wiring exists yet.

execution_mode=simulation -- this module never claims real-world
validation of any transition, reward, or action outcome it produces.

REUSE, NOT DUPLICATION: this module builds no new anomaly/trust/attribution
logic, no new prognosis inference, and no new isolation policy. It wires
together, unmodified:
  - ``edge.models.degradation_generator.SyntheticDegradationGenerator``
    (gradual wear-out telemetry -- P0 gap-closure item, increment 1)
  - ``edge.injection.injections`` (discrete faults/attacks layered on top,
    applied once over the whole generated stream at construction time,
    exactly as ``edge/eval/if_eval.py``/``swat_eval.py`` already do)
  - ``edge.pipeline.monitor.LiveP2Monitor`` (the SAME warm-up/sliding-window
    P2 wiring ``edge/main.py`` uses for the live path -- not reimplemented)
  - ``edge.pipeline.isolation_fallback.decide_isolation`` (consulted ONLY
    for diagnostic ``info``, never to drive the environment itself -- see
    ``step()``)
  - ``edge.pipeline.prognosis_runtime.PrognosisRuntime`` (optional; if
    omitted, every state's ``failure_eta`` is honestly ``None`` -- see
    ``edge.rl.state``'s missing-prognosis handling)
  - ``edge.rl.state.build_rl_state`` (FR-RL1's state vector, unmodified)

ACTION REPRESENTATION: exactly the existing, already-approved
``app.schemas.contracts.RLAction`` enum (FR-RL2 / Doc05
``decisions.rl_action``) -- not a new or provisional action type. What IS
provisional, for this first environment version only, is the GRANULARITY:
actions are modeled as device-level (one action per step, no per-channel
targeting), since neither the PRD nor any DECISIONS.md entry specifies how
"Isolate Sensor" selects WHICH sensor. Per-channel targeting already exists
elsewhere (``edge.pipeline.isolation_fallback``/``isolation_tracker``) and
can be wired in for a future environment version without changing this
module's public shape.

REWARD BOUNDARY: ``RewardSignal.total`` is always ``None`` here -- U06 (RL
reward shaping + acceptable false-isolation rate) is fully open in
DECISIONS.md; this module invents no weights. ``RewardSignal.components``
is reserved for a future increment to populate (e.g. the false-isolation/
missed-fault/downtime terms FR-RL3 names) and is always empty today.

SAFETY BOUNDARY: this module performs NO actuation. ``step(action)``
records which action was passed and reports what the EXISTING deterministic
fallback (``decide_isolation``) would have chosen, purely as diagnostic
``info`` for a future reward function -- it never invokes the P2-to-P3
self-healing adapter or orchestrator (``edge/pipeline/cycle.py``,
``edge/pipeline/self_heal.py``), any actuator or general-purpose I/O pin,
or any network/decision-publishing code, and never will inside this
module.

EPISODE CONTRACT (deliberately simple for this first version):
  - The full telemetry trajectory (degradation + injections) is generated
    ONCE at construction, from the caller-supplied, already-seeded
    ``generator``/``injections`` -- fully deterministic given that config.
  - ``reset()`` may be called ONLY ONCE per environment instance. P2's own
    ``ConsistencyProvider``/``LiveP2Monitor`` are stateful and fit-once by
    design (see ``edge/pipeline/monitor.py``) -- there is no supported way
    to "rewind" that state safely. A second ``reset()`` call raises
    ``RuntimeError``; construct a new environment instance (with a fresh
    ``pipeline``/``c_provider`` pair, mirroring
    ``edge/main.py``'s own ``_build_p2_monitor()`` construction pattern)
    for a new episode. Two separately-constructed environments built from
    identically-configured (same seed) generators/injections/pipelines
    produce identical episodes -- this is what "deterministic given a
    fixed seed" means here.
  - An episode terminates when either the trajectory's frames are
    exhausted, or the action passed to ``step()`` is
    ``RLAction.safe_stop`` -- a documented, provisional simulation rule
    (a real safe-stop ends what happens next in a run), not a claim about
    real pump behavior.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.schemas.contracts import RLAction

from edge.anomaly.pipeline import P2Pipeline, WindowOutcome
from edge.anomaly.preprocess import Preprocessor
from edge.injection.injections import Injection
from edge.models.degradation_generator import SyntheticDegradationGenerator
from edge.pipeline.isolation_fallback import decide_isolation
from edge.pipeline.monitor import LiveP2Monitor, RawChannelValues
from edge.rl.state import RLState, build_rl_state
from edge.trust.c_consistency import ConsistencyProvider

if TYPE_CHECKING:  # pragma: no cover - import-time-only, avoids a hard torch
    # dependency for callers that never pass a real PrognosisRuntime (see
    # module docstring; edge.pipeline.prognosis_runtime imports torch
    # transitively via edge.models.lstm_prognosis).
    from edge.pipeline.prognosis_runtime import PrognosisRuntime

EXECUTION_MODE = "simulation"


@dataclass(frozen=True)
class RewardSignal:
    """Placeholder reward structure -- see module docstring's REWARD
    BOUNDARY section. ``total=None`` always, until U06 is resolved."""

    components: dict[str, float] = field(default_factory=dict)
    total: float | None = None


@dataclass(frozen=True)
class EnvironmentStepResult:
    state: RLState
    reward: RewardSignal
    done: bool
    info: dict[str, object]


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
        injections: Sequence[Injection] = (),
        prognosis_runtime: PrognosisRuntime | None = None,
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

        self._cursor = 0
        self._has_reset = False
        self._done = False

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
        return self._build_state()

    def step(self, action: RLAction) -> EnvironmentStepResult:
        """Advance one tick, recording ``action`` for diagnostics only --
        no actuation, no isolation, no self-healing call is made (see
        module docstring's SAFETY BOUNDARY).

        Raises:
            RuntimeError: if called before ``reset()``, or after the
                episode has already terminated.
            ValueError: if ``action`` is not an ``RLAction`` member.
        """
        if not self._has_reset:
            raise RuntimeError("step() called before reset()")
        if self._done:
            raise RuntimeError(
                "step() called after episode termination; construct a new environment"
            )
        if not isinstance(action, RLAction):
            raise ValueError(f"action must be an RLAction, got {type(action).__name__}")

        self._feed_next_frame()
        state = self._build_state()

        exhausted = self._cursor >= len(self._frames)
        done = exhausted or action is RLAction.safe_stop
        self._done = done

        fallback_candidates: list[str] = []
        if self._latest_outcome is not None:
            fallback_candidates = sorted(decide_isolation(self._latest_outcome).isolated_channels)

        info: dict[str, object] = {
            "execution_mode": EXECUTION_MODE,
            "action_taken": action.value,
            "deterministic_fallback_would_isolate": fallback_candidates,
            "trajectory_exhausted": exhausted,
        }
        return EnvironmentStepResult(
            state=state, reward=RewardSignal(), done=done, info=info
        )

    def _build_state(self) -> RLState:
        outcome = self._latest_outcome
        raw = self._latest_raw
        assert outcome is not None and raw is not None  # guaranteed once reset() has run

        health = self._health[raw.sample_seq]

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
