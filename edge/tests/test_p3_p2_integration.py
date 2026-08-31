"""Real P2->P3 integration tests (P3 software-hardening increment).

Part A: verifies the REAL edge.anomaly.pipeline.P2Pipeline.process() ->
WindowOutcome -> edge.pipeline.cycle.process_isolated_channels() ->
real LSTMTwinReconstructor/SelfHealOrchestrator chain -- not a hand-built
stand-in WindowOutcome (that is already covered in test_lstm_twin.py). This
is a MECHANICAL INTEGRATION proof only: it shows a genuine P2Pipeline
output's actual field shapes/types satisfy what P3 expects. It is NOT a P3
acceptance or real-world validation claim, and it does NOT decide isolation
-- isolated_channels/raw_values remain explicit, hardcoded TEST FIXTURES,
never derived from outcome.trust/band (see edge/pipeline/cycle.py's own
docstring for why: FR-RL2 makes isolation an RL-agent action, and neither
the agent nor its deterministic fallback, FR-RL4, exist in this repo).

Uses NullDetector (a real, existing, hardware-free P2 component) rather
than IsolationForestDetector: this test's purpose is P2Pipeline's OUTPUT
SHAPE integrating with P3, not IF's detection behavior (already covered by
edge/tests/test_p2_acceptance.py) -- this keeps the test's dependency
surface to torch only, no sklearn guard needed.

Part B: an OBSERVATIONAL-ONLY timing measurement of one
SelfHealOrchestrator.process_isolated_channel() call (the real LSTM forward
pass + divergence + uncertainty) on THIS HOST MACHINE. It makes NO timing
assertion, introduces NO ceiling/timeout number, and does NOT validate PRD
NFR-P3's documented "<500 ms" self-healing budget -- that target is
explicitly edge/Pi-resident and measured "under load" (TRD/Doc06); nothing
about a host-machine measurement can establish or approximate on-Pi timing.

`divergence_threshold`/`substitution_max_seconds`/`hidden_size` below are
TEST FIXTURES ONLY -- never presented as project specification values
(`divergence_threshold` remains genuinely unresolved, U05). `uncertainty_
cap`/the elapsed-time scaling formula are NOT fixtures: they are the real,
D020-approved values (`UNCERTAINTY_CAP_D020` / `linear_scaling`), imported
directly rather than re-derived.

Skipped entirely when torch is unavailable -- same skip-pattern as
edge/tests/test_lstm_twin.py.
"""

from __future__ import annotations

import random
import time

import pytest

pytest.importorskip("torch")

from app.schemas.build import build_telemetry  # noqa: E402
from app.schemas.contracts import CHANNELS, TelemetryMessage  # noqa: E402

from edge.anomaly.attribution import AttributionEngine  # noqa: E402
from edge.anomaly.detector import NullDetector  # noqa: E402
from edge.anomaly.physics_rule import TrendSignPhysicsRule  # noqa: E402
from edge.anomaly.pipeline import P2Pipeline  # noqa: E402
from edge.anomaly.policy import SeverityThresholdFlagPolicy  # noqa: E402
from edge.anomaly.preprocess import Preprocessor  # noqa: E402
from edge.models.lstm_twin import LSTMTwinReconstructor, _LSTMTwinNet  # noqa: E402
from edge.pipeline.cycle import process_isolated_channels  # noqa: E402
from edge.pipeline.divergence import DivergenceScorer  # noqa: E402
from edge.pipeline.self_heal import UNCERTAINTY_CAP_D020, SelfHealOrchestrator  # noqa: E402
from edge.pipeline.uncertainty import (  # noqa: E402
    ElapsedTimeUncertaintyProxy,
    linear_scaling,
)
from edge.trust.c_consistency import ConsistencyProvider  # noqa: E402
from edge.trust.engine import TrustEngine  # noqa: E402
from edge.trust.h_reliability import HReliabilityProvider  # noqa: E402
from edge.trust.k_correlation import CorrelationProvider  # noqa: E402

# ---- TEST FIXTURES ONLY -- not project specification values ---------------
DEVICE = "pump-01"
WINDOW_SIZE = 30
STEP = 1
FLAG_POLICY_TAIL_FRACTION_FIXTURE = 0.1

DIVERGENCE_THRESHOLD_FIXTURE = 3.0
SUBSTITUTION_MAX_SECONDS_FIXTURE = 60.0
HIDDEN_SIZE_FIXTURE = 4
# uncertainty_cap/the scaling formula below are NOT fixtures: they are the
# real, D020-approved values (UNCERTAINTY_CAP_D020 / linear_scaling),
# imported directly rather than re-derived.

_BASELINE = {
    "temperature": 25.0,
    "vibration": 0.5,
    "pressure": 2.0,
    "humidity": 50.0,
    "gas": 100.0,
    "current": 1.0,
}
_NOISE_AMPLITUDE = {ch: v * 0.02 for ch, v in _BASELINE.items()}


def _ts(i: int) -> str:
    minute, second = divmod(i, 60)
    hour, minute = divmod(minute, 60)
    return f"2026-08-31T{hour:02d}:{minute:02d}:{second:02d}.000Z"


def _clean_stream(n: int, seed: int) -> list[TelemetryMessage]:
    """Deterministic clean frames -- same style as
    edge/tests/test_p2_acceptance.py's own local generator."""
    rng = random.Random(seed)
    frames = []
    for i in range(n):
        values = {
            ch: _BASELINE[ch] + rng.uniform(-_NOISE_AMPLITUDE[ch], _NOISE_AMPLITUDE[ch])
            for ch in CHANNELS
        }
        frames.append(build_telemetry(DEVICE, _ts(i), values, i))
    return frames


def _preprocessor() -> Preprocessor:
    return Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW_SIZE, step=STEP)


def _build_real_p2_pipeline() -> P2Pipeline:
    """A real P2Pipeline: real Preprocessor, NullDetector (real,
    hardware-free -- see module docstring for why not IsolationForest),
    real ConsistencyProvider/CorrelationProvider/HReliabilityProvider/
    TrustEngine/AttributionEngine with the real TrendSignPhysicsRule, real
    SeverityThresholdFlagPolicy. c_provider/flag_policy/physics_rule fit on
    a clean-baseline stream, same discipline as
    edge/tests/test_p2_acceptance.py."""
    fit_frames = _clean_stream(600, seed=1)
    fit_windows = _preprocessor().process(fit_frames)

    detector = NullDetector()
    detector.fit(fit_windows)

    c_provider = ConsistencyProvider()
    c_provider.fit(fit_windows)

    flag_policy = SeverityThresholdFlagPolicy(tail_fraction=FLAG_POLICY_TAIL_FRACTION_FIXTURE)
    flag_policy.fit(fit_windows)

    physics_rule = TrendSignPhysicsRule()
    physics_rule.fit(fit_windows)

    return P2Pipeline(
        preprocessor=_preprocessor(),
        detector=detector,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(physics_rule),
        c_provider=c_provider,
        k_provider=CorrelationProvider(),
        h_provider=HReliabilityProvider(),
        flag_policy=flag_policy,
    )


def _make_self_heal_orchestrator():
    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    twin = LSTMTwinReconstructor(network)
    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    calls = {"n": 0}

    def safe_stop():
        calls["n"] += 1

    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=safe_stop,
        substitution_max_seconds=SUBSTITUTION_MAX_SECONDS_FIXTURE,
    )
    return orchestrator, calls


# ---------------------------------------------------------------------------
# Part A: real P2Pipeline output -> process_isolated_channels
# ---------------------------------------------------------------------------


def test_real_p2_pipeline_output_flows_through_process_isolated_channels():
    """Mechanical integration proof, NOT a P3 acceptance/accuracy claim --
    see module docstring."""
    pipeline = _build_real_p2_pipeline()
    eval_frames = _clean_stream(40, seed=2)
    outcomes = pipeline.process(eval_frames)
    assert outcomes, "expected at least one WindowOutcome from a 40-frame stream"
    outcome = outcomes[-1]

    orchestrator, _calls = _make_self_heal_orchestrator()

    results = process_isolated_channels(
        outcome,
        isolated_channels={"temperature"},
        raw_values={"temperature": 25.0},
        orchestrator=orchestrator,
    )

    assert set(results.keys()) == {"temperature"}
    result = results["temperature"]
    assert isinstance(result.substituted, bool)
    assert isinstance(result.escalated, bool)
    if result.substituted:
        assert isinstance(result.reconstructed_value, float)
        assert result.divergence is not None
        assert result.uncertainty is not None
    else:
        # Recovery is an equally valid integration proof: it means the
        # REAL trust value P2Pipeline computed for "temperature" on this
        # clean stream was already >= TRUSTED_MIN, and that real value
        # correctly reached and drove SelfHealOrchestrator's own recovery
        # decision -- exactly the same shape/flow proof either way.
        assert result.reconstructed_value is None
        assert result.divergence is None
        assert result.uncertainty is None


# ---------------------------------------------------------------------------
# Part B: FR-H4 timing -- OBSERVATIONAL ONLY, no assertion, no ceiling
# ---------------------------------------------------------------------------


def test_self_heal_call_timing_observational_host_only():
    """OBSERVATIONAL ONLY -- no timing assertion, no ceiling, no threshold.

    Measures the wall-clock elapsed time of one process_isolated_channel()
    call (real LSTM forward pass + divergence + uncertainty) on THIS HOST
    MACHINE. This does NOT validate PRD NFR-P3's documented <500 ms
    edge/Pi self-healing budget and is not a hardware timing claim -- see
    module docstring. This test cannot fail on timing; it only proves the
    call completes and returns a well-formed outcome.
    """
    orchestrator, _calls = _make_self_heal_orchestrator()
    window = _preprocessor().process(_clean_stream(30, seed=3))[0]

    start = time.perf_counter()
    outcome = orchestrator.process_isolated_channel(
        "temperature", window, raw_value=25.0, trust=0.2
    )
    elapsed_seconds = time.perf_counter() - start

    # No assertion on elapsed_seconds -- observational only, per design.
    print(
        f"[observational, host-machine only, NOT NFR-P3] "
        f"process_isolated_channel elapsed: {elapsed_seconds * 1000:.2f} ms"
    )
    assert isinstance(outcome.reconstructed_value, float)
