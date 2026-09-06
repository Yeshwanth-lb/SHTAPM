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

INJECTION-TYPE SCENARIO TAXONOMY (U06 scoping -- see ``project-state/
DECISIONS.md``'s "U06 -- Operational Definitions Proposal" and its
scenario-taxonomy implementation plan): one held-out evaluation scenario
per ``edge.injection.injections.InjectionType`` member now exists below
(``SCENARIO_INJECTED_CURRENT_SPIKE`` plus seven new siblings), each
single-channel, reusing the same degradation profile
``SCENARIO_CLEAN_DEGRADATION`` already uses. ``EVALUATION_SCENARIO_
METADATA`` (below) is a purely descriptive, additive lookup -- it changes
no existing ``ScenarioConfig`` field, no constructor, and no function
signature; it exists only so a reader/future harness does not need to
reconstruct each scenario's classification and injection parameters from
``scenario.injections[0].__dict__`` by hand. NONE of this wires any
ground-truth comparison, rate calculation, or reward change -- see U06's
own still-fully-open status in ``DECISIONS.md``. KNOWN, INTENTIONAL GAPS
(not addressed by this increment): every scenario here injects at most one
channel with at most one fault/attack -- no simultaneous multi-channel or
multi-fault scenario exists; no scenario besides ``SCENARIO_CLEAN_
DEGRADATION`` covers a degradation profile other than the one shared shape
reused throughout this taxonomy.

INJECTION-LABEL RETENTION (U06 scoping, follow-up increment -- see
``edge.rl.environment``'s own INJECTION-LABEL RETENTION docstring section):
``edge.rl.environment.SHTAPMSimulationEnvironment`` now retains each
injection's ``InjectionResult.labels`` (previously discarded) and exposes
each step's ``sample_seq`` in ``EnvironmentStepResult.info``. This module's
``TransitionRecord`` gains one new, defaulted, purely descriptive field,
``active_injection_labels`` (a tuple of raw ``injection_type`` name strings
active at that step's ``sample_seq``, e.g. ``("spike",)``) -- populated in
``_run_episode`` from ``result.info["sample_seq"]`` joined against the
environment's own retained labels. This is NOT a false-isolation or
missed-fault verdict, NOT a rate, and NOT a comparison against
``safety_status``/``requested_action``/etc. -- no such comparison is
implemented anywhere in this module. U06 remains fully open (see
``DECISIONS.md``).
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
from edge.injection.injections import (
    AdaptiveStealthFDI,
    BiasFDI,
    ConstantSpoof,
    Drift,
    Injection,
    InjectionType,
    RampFDI,
    Replay,
    Spike,
    StuckAt,
)
from edge.models.degradation_generator import (
    ChannelDegradationConfig,
    SyntheticDegradationGenerator,
)
from edge.rl.environment import SHTAPMSimulationEnvironment
from edge.rl.fallback_gate import RL_CONFIDENCE_THRESHOLD_FIXTURE
from edge.rl.policy import BASELINE_CRITICAL_HEALTH_FIXTURE, BaselinePolicy
from edge.rl.reward import SIMULATION_REWARD_WEIGHTS_FIXTURE, RewardWeights
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

# ---- Seed-repetition variants of SCENARIO_CLEAN_DEGRADATION (U06 scoping) --
# Four additional scenarios reusing SCENARIO_CLEAN_DEGRADATION's own profile
# EXACTLY (length, health range, degradation rate, vibration config, no
# injections) -- only ``seed`` differs. Together with the original, these
# five scenarios establish the first complete 5-seed coverage pattern for
# one scenario shape, per the "U06 -- Operational Definitions Proposal"'s
# own section D (proposed minimum: at least 5 distinct seeds per scenario).
# Seeds 1346-1349 -- distinct from every existing evaluation-scenario seed
# (1337-1345), every TRAINING_SCENARIOS seed (2001, 2002), and
# edge.eval.rl_training.SEED_FIXTURE (1337, a training-run RNG seed,
# unrelated to any ScenarioConfig). Not added to INJECTION_TYPE_SCENARIOS,
# EVALUATION_SCENARIO_METADATA, or default_scenarios() -- consumed
# explicitly by edge.eval.u06_seed_repetition_report instead, exactly as
# INJECTION_TYPE_SCENARIOS is consumed explicitly by
# edge.eval.rl_training.EVALUATION_SCENARIOS rather than folded into
# default_scenarios().
SCENARIO_CLEAN_DEGRADATION_SEED_1346 = ScenarioConfig(
    name="clean_degradation_seed_1346",
    seed=1346,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(),
)

SCENARIO_CLEAN_DEGRADATION_SEED_1347 = ScenarioConfig(
    name="clean_degradation_seed_1347",
    seed=1347,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(),
)

SCENARIO_CLEAN_DEGRADATION_SEED_1348 = ScenarioConfig(
    name="clean_degradation_seed_1348",
    seed=1348,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(),
)

SCENARIO_CLEAN_DEGRADATION_SEED_1349 = ScenarioConfig(
    name="clean_degradation_seed_1349",
    seed=1349,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(),
)

# All 5 clean-degradation seed variants, including the original -- consumed
# by edge.eval.u06_seed_repetition_report. Order is fixed and deterministic.
CLEAN_DEGRADATION_SEED_REPETITION_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_CLEAN_DEGRADATION_SEED_1346,
    SCENARIO_CLEAN_DEGRADATION_SEED_1347,
    SCENARIO_CLEAN_DEGRADATION_SEED_1348,
    SCENARIO_CLEAN_DEGRADATION_SEED_1349,
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

# ---- Seed-repetition variants of SCENARIO_INJECTED_CURRENT_SPIKE (U06
# scoping) -- second scenario shape covered by this pattern, after
# SCENARIO_CLEAN_DEGRADATION's own 5-seed set above. Four additional
# scenarios reusing SCENARIO_INJECTED_CURRENT_SPIKE's own profile EXACTLY
# (length, health range, degradation rate, vibration config, and its
# Spike injection unchanged) -- only ``seed`` differs. Per the "U06 --
# Operational Definitions Proposal"'s own section D (proposed minimum: at
# least 5 distinct seeds per scenario), still only 2 of 9 scenarios now
# have 5-seed coverage; the remaining 7 injection-type scenarios remain
# unfinished. Seeds 1350-1353 -- distinct from every existing evaluation-
# scenario seed (1337-1349), every TRAINING_SCENARIOS seed (2001, 2002),
# and edge.eval.rl_training.SEED_FIXTURE (1337, a training-run RNG seed,
# unrelated to any ScenarioConfig). Not added to INJECTION_TYPE_SCENARIOS,
# EVALUATION_SCENARIO_METADATA, or default_scenarios() -- consumed
# explicitly by edge.eval.u06_seed_repetition_report_injected_current_spike
# instead, matching CLEAN_DEGRADATION_SEED_REPETITION_SCENARIOS' own
# convention.
SCENARIO_INJECTED_CURRENT_SPIKE_SEED_1350 = ScenarioConfig(
    name="injected_current_spike_seed_1350",
    seed=1350,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(Spike(channel="current", onset=32, duration=5, amplitude=50.0),),
)

SCENARIO_INJECTED_CURRENT_SPIKE_SEED_1351 = ScenarioConfig(
    name="injected_current_spike_seed_1351",
    seed=1351,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(Spike(channel="current", onset=32, duration=5, amplitude=50.0),),
)

SCENARIO_INJECTED_CURRENT_SPIKE_SEED_1352 = ScenarioConfig(
    name="injected_current_spike_seed_1352",
    seed=1352,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(Spike(channel="current", onset=32, duration=5, amplitude=50.0),),
)

SCENARIO_INJECTED_CURRENT_SPIKE_SEED_1353 = ScenarioConfig(
    name="injected_current_spike_seed_1353",
    seed=1353,
    length=40,
    start_health=1.0,
    end_health=0.2,
    degradation_rate=1.0,
    channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
    injections=(Spike(channel="current", onset=32, duration=5, amplitude=50.0),),
)

# All 5 injected_current_spike seed variants, including the original --
# consumed by edge.eval.u06_seed_repetition_report_injected_current_spike.
# Order is fixed and deterministic.
INJECTED_CURRENT_SPIKE_SEED_REPETITION_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_INJECTED_CURRENT_SPIKE,
    SCENARIO_INJECTED_CURRENT_SPIKE_SEED_1350,
    SCENARIO_INJECTED_CURRENT_SPIKE_SEED_1351,
    SCENARIO_INJECTED_CURRENT_SPIKE_SEED_1352,
    SCENARIO_INJECTED_CURRENT_SPIKE_SEED_1353,
)

# ---- One held-out evaluation scenario per InjectionType (U06 scoping) -----
# Each reuses SCENARIO_CLEAN_DEGRADATION's own degradation profile (length,
# health range, degradation rate, vibration config) unchanged, varying only
# the single injected channel/fault. Seeds 1339-1345 -- distinct from every
# TRAINING_SCENARIOS seed (2001, 2002) and from 1337/1338 above. See module
# docstring's INJECTION-TYPE SCENARIO TAXONOMY section for scope and gaps.
_EVALUATION_DEGRADATION_PROFILE = {
    "start_health": 1.0,
    "end_health": 0.2,
    "degradation_rate": 1.0,
    "channels": {"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
}

SCENARIO_INJECTED_TEMPERATURE_DRIFT = ScenarioConfig(
    name="injected_temperature_drift",
    seed=1339,
    length=40,
    injections=(Drift(channel="temperature", onset=30, duration=5, rate=0.5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

# ---- Seed-repetition variants of SCENARIO_INJECTED_TEMPERATURE_DRIFT (U06
# scoping) -- third scenario shape covered by this pattern, after
# SCENARIO_CLEAN_DEGRADATION's and SCENARIO_INJECTED_CURRENT_SPIKE's own
# 5-seed sets. Four additional scenarios reusing
# SCENARIO_INJECTED_TEMPERATURE_DRIFT's own profile EXACTLY (length, health
# range, degradation rate, vibration config, and its Drift injection
# unchanged) -- only ``seed`` differs. Per the "U06 -- Operational
# Definitions Proposal"'s own section D (proposed minimum: at least 5
# distinct seeds per scenario), still only 3 of 9 scenarios now have 5-seed
# coverage; the remaining 6 injection-type scenarios remain unfinished.
# Seeds 1354-1357 -- distinct from every existing evaluation-scenario seed
# (1337-1353), every TRAINING_SCENARIOS seed (2001, 2002), and
# edge.eval.rl_training.SEED_FIXTURE (1337, a training-run RNG seed,
# unrelated to any ScenarioConfig). Not added to INJECTION_TYPE_SCENARIOS,
# EVALUATION_SCENARIO_METADATA, or default_scenarios() -- consumed
# explicitly by edge.eval.u06_seed_repetition_report_injected_temperature_drift
# instead, matching the two prior seed-repetition sets' own convention.
SCENARIO_INJECTED_TEMPERATURE_DRIFT_SEED_1354 = ScenarioConfig(
    name="injected_temperature_drift_seed_1354",
    seed=1354,
    length=40,
    injections=(Drift(channel="temperature", onset=30, duration=5, rate=0.5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_TEMPERATURE_DRIFT_SEED_1355 = ScenarioConfig(
    name="injected_temperature_drift_seed_1355",
    seed=1355,
    length=40,
    injections=(Drift(channel="temperature", onset=30, duration=5, rate=0.5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_TEMPERATURE_DRIFT_SEED_1356 = ScenarioConfig(
    name="injected_temperature_drift_seed_1356",
    seed=1356,
    length=40,
    injections=(Drift(channel="temperature", onset=30, duration=5, rate=0.5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_TEMPERATURE_DRIFT_SEED_1357 = ScenarioConfig(
    name="injected_temperature_drift_seed_1357",
    seed=1357,
    length=40,
    injections=(Drift(channel="temperature", onset=30, duration=5, rate=0.5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

# All 5 injected_temperature_drift seed variants, including the original --
# consumed by edge.eval.u06_seed_repetition_report_injected_temperature_drift.
# Order is fixed and deterministic.
INJECTED_TEMPERATURE_DRIFT_SEED_REPETITION_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_INJECTED_TEMPERATURE_DRIFT,
    SCENARIO_INJECTED_TEMPERATURE_DRIFT_SEED_1354,
    SCENARIO_INJECTED_TEMPERATURE_DRIFT_SEED_1355,
    SCENARIO_INJECTED_TEMPERATURE_DRIFT_SEED_1356,
    SCENARIO_INJECTED_TEMPERATURE_DRIFT_SEED_1357,
)

SCENARIO_INJECTED_PRESSURE_STUCK_AT = ScenarioConfig(
    name="injected_pressure_stuck_at",
    seed=1340,
    length=40,
    injections=(StuckAt(channel="pressure", onset=30, duration=5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

# ---- Seed-repetition variants of SCENARIO_INJECTED_PRESSURE_STUCK_AT (U06
# scoping) -- fourth scenario shape covered by this pattern, after
# SCENARIO_CLEAN_DEGRADATION's, SCENARIO_INJECTED_CURRENT_SPIKE's, and
# SCENARIO_INJECTED_TEMPERATURE_DRIFT's own 5-seed sets. Four additional
# scenarios reusing SCENARIO_INJECTED_PRESSURE_STUCK_AT's own profile
# EXACTLY (length, health range, degradation rate, vibration config, and
# its StuckAt injection unchanged) -- only ``seed`` differs. Per the "U06
# -- Operational Definitions Proposal"'s own section D (proposed minimum:
# at least 5 distinct seeds per scenario), still only 4 of 9 scenarios now
# have 5-seed coverage; the remaining 5 injection-type scenarios remain
# unfinished. Seeds 1358-1361 -- distinct from every existing evaluation-
# scenario seed (1337-1357), every TRAINING_SCENARIOS seed (2001, 2002),
# and edge.eval.rl_training.SEED_FIXTURE (1337, a training-run RNG seed,
# unrelated to any ScenarioConfig). Not added to INJECTION_TYPE_SCENARIOS,
# EVALUATION_SCENARIO_METADATA, or default_scenarios() -- consumed
# explicitly by edge.eval.u06_seed_repetition_report_injected_pressure_stuck_at
# instead, matching the three prior seed-repetition sets' own convention.
SCENARIO_INJECTED_PRESSURE_STUCK_AT_SEED_1358 = ScenarioConfig(
    name="injected_pressure_stuck_at_seed_1358",
    seed=1358,
    length=40,
    injections=(StuckAt(channel="pressure", onset=30, duration=5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_PRESSURE_STUCK_AT_SEED_1359 = ScenarioConfig(
    name="injected_pressure_stuck_at_seed_1359",
    seed=1359,
    length=40,
    injections=(StuckAt(channel="pressure", onset=30, duration=5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_PRESSURE_STUCK_AT_SEED_1360 = ScenarioConfig(
    name="injected_pressure_stuck_at_seed_1360",
    seed=1360,
    length=40,
    injections=(StuckAt(channel="pressure", onset=30, duration=5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_PRESSURE_STUCK_AT_SEED_1361 = ScenarioConfig(
    name="injected_pressure_stuck_at_seed_1361",
    seed=1361,
    length=40,
    injections=(StuckAt(channel="pressure", onset=30, duration=5),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

# All 5 injected_pressure_stuck_at seed variants, including the original --
# consumed by edge.eval.u06_seed_repetition_report_injected_pressure_stuck_at.
# Order is fixed and deterministic.
INJECTED_PRESSURE_STUCK_AT_SEED_REPETITION_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_INJECTED_PRESSURE_STUCK_AT,
    SCENARIO_INJECTED_PRESSURE_STUCK_AT_SEED_1358,
    SCENARIO_INJECTED_PRESSURE_STUCK_AT_SEED_1359,
    SCENARIO_INJECTED_PRESSURE_STUCK_AT_SEED_1360,
    SCENARIO_INJECTED_PRESSURE_STUCK_AT_SEED_1361,
)

SCENARIO_INJECTED_HUMIDITY_BIAS_FDI = ScenarioConfig(
    name="injected_humidity_bias_fdi",
    seed=1341,
    length=40,
    injections=(BiasFDI(channel="humidity", onset=30, duration=5, bias=5.0),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

# ---- Seed-repetition variants of SCENARIO_INJECTED_HUMIDITY_BIAS_FDI (U06
# scoping) -- fifth scenario shape covered by this pattern, after
# SCENARIO_CLEAN_DEGRADATION's, SCENARIO_INJECTED_CURRENT_SPIKE's,
# SCENARIO_INJECTED_TEMPERATURE_DRIFT's, and
# SCENARIO_INJECTED_PRESSURE_STUCK_AT's own 5-seed sets. Four additional
# scenarios reusing SCENARIO_INJECTED_HUMIDITY_BIAS_FDI's own profile
# EXACTLY (length, health range, degradation rate, vibration config, and
# its BiasFDI injection unchanged) -- only ``seed`` differs. Per the "U06
# -- Operational Definitions Proposal"'s own section D (proposed minimum:
# at least 5 distinct seeds per scenario), still only 5 of 9 scenarios now
# have 5-seed coverage; the remaining 4 injection-type scenarios remain
# unfinished. Seeds 1362-1365 -- distinct from every existing evaluation-
# scenario seed (1337-1361), every TRAINING_SCENARIOS seed (2001, 2002),
# and edge.eval.rl_training.SEED_FIXTURE (1337, a training-run RNG seed,
# unrelated to any ScenarioConfig). Not added to INJECTION_TYPE_SCENARIOS,
# EVALUATION_SCENARIO_METADATA, or default_scenarios() -- consumed
# explicitly by edge.eval.u06_seed_repetition_report_injected_humidity_bias_fdi
# instead, matching the four prior seed-repetition sets' own convention.
SCENARIO_INJECTED_HUMIDITY_BIAS_FDI_SEED_1362 = ScenarioConfig(
    name="injected_humidity_bias_fdi_seed_1362",
    seed=1362,
    length=40,
    injections=(BiasFDI(channel="humidity", onset=30, duration=5, bias=5.0),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_HUMIDITY_BIAS_FDI_SEED_1363 = ScenarioConfig(
    name="injected_humidity_bias_fdi_seed_1363",
    seed=1363,
    length=40,
    injections=(BiasFDI(channel="humidity", onset=30, duration=5, bias=5.0),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_HUMIDITY_BIAS_FDI_SEED_1364 = ScenarioConfig(
    name="injected_humidity_bias_fdi_seed_1364",
    seed=1364,
    length=40,
    injections=(BiasFDI(channel="humidity", onset=30, duration=5, bias=5.0),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_HUMIDITY_BIAS_FDI_SEED_1365 = ScenarioConfig(
    name="injected_humidity_bias_fdi_seed_1365",
    seed=1365,
    length=40,
    injections=(BiasFDI(channel="humidity", onset=30, duration=5, bias=5.0),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

# All 5 injected_humidity_bias_fdi seed variants, including the original --
# consumed by edge.eval.u06_seed_repetition_report_injected_humidity_bias_fdi.
# Order is fixed and deterministic.
INJECTED_HUMIDITY_BIAS_FDI_SEED_REPETITION_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_INJECTED_HUMIDITY_BIAS_FDI,
    SCENARIO_INJECTED_HUMIDITY_BIAS_FDI_SEED_1362,
    SCENARIO_INJECTED_HUMIDITY_BIAS_FDI_SEED_1363,
    SCENARIO_INJECTED_HUMIDITY_BIAS_FDI_SEED_1364,
    SCENARIO_INJECTED_HUMIDITY_BIAS_FDI_SEED_1365,
)

SCENARIO_INJECTED_GAS_RAMP_FDI = ScenarioConfig(
    name="injected_gas_ramp_fdi",
    seed=1342,
    length=40,
    injections=(RampFDI(channel="gas", onset=28, duration=8, slope=0.8),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_VIBRATION_REPLAY = ScenarioConfig(
    name="injected_vibration_replay",
    seed=1343,
    length=40,
    # source segment [0, 5) ends at 5, at/before onset=30 -- satisfies
    # Replay._validate_against()'s own "source must end at or before onset"
    # and in-bounds-of-stream requirements (see edge/injection/injections.py).
    injections=(Replay(channel="vibration", onset=30, duration=5, source_onset=0),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF = ScenarioConfig(
    name="injected_current_constant_spoof",
    seed=1344,
    length=40,
    injections=(ConstantSpoof(channel="current", onset=30, duration=5, value=0.0),),
    **_EVALUATION_DEGRADATION_PROFILE,
)

SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI = ScenarioConfig(
    name="injected_temperature_adaptive_stealth_fdi",
    seed=1345,
    length=40,
    injections=(
        AdaptiveStealthFDI(
            channel="temperature", onset=25, duration=10, rate=0.5, residual_cap=2.0
        ),
    ),
    **_EVALUATION_DEGRADATION_PROFILE,
)

# All 8 InjectionType-covering scenarios, in InjectionType declaration order
# (edge/injection/injections.py's own DRIFT/SPIKE/STUCK_AT/BIAS_FDI/RAMP_FDI/
# REPLAY/CONSTANT_SPOOF/ADAPTIVE_STEALTH_FDI ordering) -- NOT included in
# default_scenarios() (unchanged below); consumed explicitly by
# edge.eval.rl_training.EVALUATION_SCENARIOS instead.
INJECTION_TYPE_SCENARIOS: tuple[ScenarioConfig, ...] = (
    SCENARIO_INJECTED_TEMPERATURE_DRIFT,
    SCENARIO_INJECTED_CURRENT_SPIKE,
    SCENARIO_INJECTED_PRESSURE_STUCK_AT,
    SCENARIO_INJECTED_HUMIDITY_BIAS_FDI,
    SCENARIO_INJECTED_GAS_RAMP_FDI,
    SCENARIO_INJECTED_VIBRATION_REPLAY,
    SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF,
    SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI,
)


@dataclass(frozen=True)
class ScenarioMetadata:
    """Purely descriptive, additive documentation for one evaluation
    scenario -- changes no ``ScenarioConfig`` field, constructor, or
    function signature anywhere. Simulation-only (see module docstring):
    never a claim about real pump/sensor/attack behavior, and never itself
    a false-isolation/missed-fault measurement -- U06 remains fully open
    (see ``project-state/DECISIONS.md``)."""

    name: str
    purpose: str
    classification: str  # "clean" | "fault" | "attack"
    injection_type: InjectionType | None
    affected_channel: str | None
    onset: int | None
    duration: int | None
    parameters: Mapping[str, float] | None
    expected_active_window: tuple[int, int] | None
    scenario_set: str  # "training" | "evaluation"
    known_limitations: str


# One entry per evaluation scenario named above (plus SCENARIO_CLEAN_
# DEGRADATION) -- keyed by ScenarioConfig.name. Not consumed by any
# production or training code path; a reference table only.
EVALUATION_SCENARIO_METADATA: dict[str, ScenarioMetadata] = {
    SCENARIO_CLEAN_DEGRADATION.name: ScenarioMetadata(
        name=SCENARIO_CLEAN_DEGRADATION.name,
        purpose="Zero-fault baseline: wear-out degradation only, no injection.",
        classification="clean",
        injection_type=None,
        affected_channel=None,
        onset=None,
        duration=None,
        parameters=None,
        expected_active_window=None,
        scenario_set="evaluation",
        known_limitations="Single degradation profile only; no injection of any kind.",
    ),
    SCENARIO_INJECTED_CURRENT_SPIKE.name: ScenarioMetadata(
        name=SCENARIO_INJECTED_CURRENT_SPIKE.name,
        purpose="Fault-type coverage: sudden additive spike on current.",
        classification="fault",
        injection_type=InjectionType.SPIKE,
        affected_channel="current",
        onset=32,
        duration=5,
        parameters={"amplitude": 50.0},
        expected_active_window=(32, 37),
        scenario_set="evaluation",
        known_limitations="Single-channel, single-fault only; no multi-channel/multi-fault case.",
    ),
    SCENARIO_INJECTED_TEMPERATURE_DRIFT.name: ScenarioMetadata(
        name=SCENARIO_INJECTED_TEMPERATURE_DRIFT.name,
        purpose="Fault-type coverage: gradual additive drift on temperature.",
        classification="fault",
        injection_type=InjectionType.DRIFT,
        affected_channel="temperature",
        onset=30,
        duration=5,
        parameters={"rate": 0.5},
        expected_active_window=(30, 35),
        scenario_set="evaluation",
        known_limitations="Single-channel, single-fault only; no multi-channel/multi-fault case.",
    ),
    SCENARIO_INJECTED_PRESSURE_STUCK_AT.name: ScenarioMetadata(
        name=SCENARIO_INJECTED_PRESSURE_STUCK_AT.name,
        purpose="Fault-type coverage: sensor freezes at its value on pressure.",
        classification="fault",
        injection_type=InjectionType.STUCK_AT,
        affected_channel="pressure",
        onset=30,
        duration=5,
        parameters={},
        expected_active_window=(30, 35),
        scenario_set="evaluation",
        known_limitations=(
            "Single-channel, single-fault only; default held_value (value at onset), "
            "not an explicit override."
        ),
    ),
    SCENARIO_INJECTED_HUMIDITY_BIAS_FDI.name: ScenarioMetadata(
        name=SCENARIO_INJECTED_HUMIDITY_BIAS_FDI.name,
        purpose="Attack-type coverage: constant additive bias false-data-injection on humidity.",
        classification="attack",
        injection_type=InjectionType.BIAS_FDI,
        affected_channel="humidity",
        onset=30,
        duration=5,
        parameters={"bias": 5.0},
        expected_active_window=(30, 35),
        scenario_set="evaluation",
        known_limitations="Single-channel, single-attack only; no multi-channel/multi-fault case.",
    ),
    SCENARIO_INJECTED_GAS_RAMP_FDI.name: ScenarioMetadata(
        name=SCENARIO_INJECTED_GAS_RAMP_FDI.name,
        purpose="Attack-type coverage: cumulative ramping false-data-injection on gas.",
        classification="attack",
        injection_type=InjectionType.RAMP_FDI,
        affected_channel="gas",
        onset=28,
        duration=8,
        parameters={"slope": 0.8},
        expected_active_window=(28, 36),
        scenario_set="evaluation",
        known_limitations="Single-channel, single-attack only; no multi-channel/multi-fault case.",
    ),
    SCENARIO_INJECTED_VIBRATION_REPLAY.name: ScenarioMetadata(
        name=SCENARIO_INJECTED_VIBRATION_REPLAY.name,
        purpose="Attack-type coverage: replay of earlier own-channel values on vibration.",
        classification="attack",
        injection_type=InjectionType.REPLAY,
        affected_channel="vibration",
        onset=30,
        duration=5,
        parameters={"source_onset": 0.0},
        expected_active_window=(30, 35),
        scenario_set="evaluation",
        known_limitations=(
            "Single-channel, single-attack only; replayed segment is pre-degradation "
            "(source_onset=0), not a later/more-degraded segment."
        ),
    ),
    SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF.name: ScenarioMetadata(
        name=SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF.name,
        purpose="Attack-type coverage: pin to a constant spoofed value on current.",
        classification="attack",
        injection_type=InjectionType.CONSTANT_SPOOF,
        affected_channel="current",
        onset=30,
        duration=5,
        parameters={"value": 0.0},
        expected_active_window=(30, 35),
        scenario_set="evaluation",
        known_limitations="Single-channel, single-attack only; no multi-channel/multi-fault case.",
    ),
    SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.name: ScenarioMetadata(
        name=SCENARIO_INJECTED_TEMPERATURE_ADAPTIVE_STEALTH_FDI.name,
        purpose="Attack-type coverage: bias that grows then caps below a fixed residual bound.",
        classification="attack",
        injection_type=InjectionType.ADAPTIVE_STEALTH_FDI,
        affected_channel="temperature",
        onset=25,
        duration=10,
        parameters={"rate": 0.5, "residual_cap": 2.0},
        expected_active_window=(25, 35),
        scenario_set="evaluation",
        known_limitations="Single-channel, single-attack only; no multi-channel/multi-fault case.",
    ),
}


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
    # Descriptive, raw injection-type facts only (e.g. "spike") active at this
    # step's sample_seq -- NOT a false-isolation/missed-fault verdict, NOT a
    # rate, NOT a comparison result. See edge/rl/environment.py's own
    # INJECTION-LABEL RETENTION docstring section (U06 scoping). Defaulted so
    # every existing TransitionRecord construction call site is unaffected.
    active_injection_labels: tuple[str, ...] = ()
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


def _build_environment(
    scenario: ScenarioConfig,
    *,
    reward_weights: RewardWeights = SIMULATION_REWARD_WEIGHTS_FIXTURE,
) -> SHTAPMSimulationEnvironment:
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
        reward_weights=reward_weights,
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
    reward_weights: RewardWeights = SIMULATION_REWARD_WEIGHTS_FIXTURE,
) -> EpisodeRecord:
    """Shared episode-driving loop for both baselines. ``propose_action``
    is called once per step with the CURRENT ``RLState`` and must return
    ``(action, policy_available, policy_validated, confidence)`` -- the
    exact keyword shape ``SHTAPMSimulationEnvironment.step()`` already
    accepts. Neither baseline's own action-selection logic lives here;
    this function only drives the loop and records results.

    ``reward_weights`` defaults to ``SIMULATION_REWARD_WEIGHTS_FIXTURE`` --
    passing a different ``edge.rl.reward.RewardWeights`` (e.g. one of the
    named candidate configurations) changes only how this episode's reward
    totals are computed, never the scenario, the transition, or the gate."""
    env = _build_environment(scenario, reward_weights=reward_weights)
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
        # Descriptive-only, raw injection-ground-truth facts for this step's
        # sample_seq (result.info["sample_seq"] -- see edge/rl/environment.py's
        # INJECTION-LABEL RETENTION docstring section, U06 scoping). NOT a
        # false-isolation/missed-fault verdict, rate, or comparison result.
        sample_seq = result.info["sample_seq"]
        active_labels = (
            env._labels_by_sample_seq.get(sample_seq, ()) if sample_seq is not None else ()
        )
        active_injection_labels = tuple(label.injection_type.value for label in active_labels)
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
                active_injection_labels=active_injection_labels,
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


def run_baseline_policy_episode(
    scenario: ScenarioConfig,
    *,
    reward_weights: RewardWeights = SIMULATION_REWARD_WEIGHTS_FIXTURE,
) -> EpisodeRecord:
    """Run ``edge.rl.policy.BaselinePolicy`` (the existing, unmodified
    deterministic rule set) through one scenario. ``reward_weights``
    defaults to ``SIMULATION_REWARD_WEIGHTS_FIXTURE`` -- unchanged existing
    behavior when not overridden."""
    policy = BaselinePolicy(critical_health_threshold=BASELINE_CRITICAL_HEALTH_FIXTURE)

    def _propose(state):
        decision = policy.propose(state)
        return (
            decision.proposed_action,
            decision.policy_available,
            decision.policy_validated,
            decision.confidence,
        )

    return _run_episode(
        scenario, "baseline_policy", propose_action=_propose, reward_weights=reward_weights
    )


def run_pure_fallback_episode(
    scenario: ScenarioConfig,
    *,
    reward_weights: RewardWeights = SIMULATION_REWARD_WEIGHTS_FIXTURE,
) -> EpisodeRecord:
    """Run with NO policy at all -- ``policy_available=False`` on every
    step (FR-RL4 / P3-RL-S1's own scenario). ``None`` is passed as the
    requested action -- see module docstring's REQUESTED ACTION section
    for why this is not a fabrication or a gate bypass. ``reward_weights``
    defaults to ``SIMULATION_REWARD_WEIGHTS_FIXTURE`` -- unchanged existing
    behavior when not overridden."""

    def _propose(_state):
        return (None, False, False, None)

    return _run_episode(
        scenario, "pure_fallback", propose_action=_propose, reward_weights=reward_weights
    )


def run_all_baselines(
    scenarios: Sequence[ScenarioConfig] | None = None,
    *,
    reward_weights: RewardWeights = SIMULATION_REWARD_WEIGHTS_FIXTURE,
) -> list[EpisodeRecord]:
    """Run both baselines over every scenario (default: ``default_scenarios()``).
    Small callable diagnostic entry point -- NOT a production composition-root
    integration. ``reward_weights`` defaults to
    ``SIMULATION_REWARD_WEIGHTS_FIXTURE`` -- unchanged existing behavior
    when not overridden."""
    scenarios = scenarios if scenarios is not None else default_scenarios()
    records: list[EpisodeRecord] = []
    for scenario in scenarios:
        records.append(run_baseline_policy_episode(scenario, reward_weights=reward_weights))
        records.append(run_pure_fallback_episode(scenario, reward_weights=reward_weights))
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
