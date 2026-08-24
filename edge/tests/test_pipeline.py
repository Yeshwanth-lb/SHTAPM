"""P2 tests — hardware-free pipeline orchestrator (architecture/interface only).

Prove the components wire together: frames -> preprocessing -> window ->
anomaly -> trust -> attribution. All detectors/providers/rules/policies are
deterministic stubs (NullDetector, constant/mapping providers, stub physics
rule, fixed flag policy). These tests make NO claim about detection accuracy or
any P2 acceptance gate.
"""

from collections.abc import Mapping

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.attribution import AttributionEngine, PhysicsCheck
from edge.anomaly.detector import AnomalyResult, NullDetector
from edge.anomaly.pipeline import ChannelFlagPolicy, P2Pipeline, WindowOutcome
from edge.anomaly.preprocess import Preprocessor, Window
from edge.trust.engine import TrustEngine

DEVICE = "pump-01"


# --- deterministic stubs (TEST ONLY — no real detection/physics/signals) ----
class ConstantSignalProvider:
    """Test stub: always returns a constant score; record_window/outcome are no-ops."""

    def __init__(self, score: float) -> None:
        self.score = score

    def evaluate(self, channel: str) -> float:
        return self.score

    def record_window(self, window) -> None:
        """No-op for testing."""
        pass

    def record_outcome(self, channel: str, was_healthy: bool) -> None:
        """No-op for testing."""
        pass


class MappingSignalProvider:
    """Test stub: returns pre-mapped channel scores; record_window/outcome are no-ops."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def evaluate(self, channel: str) -> float:
        return self.scores[channel]

    def record_window(self, window) -> None:
        """No-op for testing."""
        pass

    def record_outcome(self, channel: str, was_healthy: bool) -> None:
        """No-op for testing."""
        pass


class StubPhysicsRule:
    def __init__(self, violated: bool, suspect_channel=None, reason: str = "") -> None:
        self._result = PhysicsCheck(violated, suspect_channel, reason)

    def check(self, window: Window) -> PhysicsCheck:
        return self._result


class FixedFlagPolicy:
    """Returns a fixed per-channel flag map regardless of the window."""

    def __init__(self, flagged: tuple[str, ...] = ()) -> None:
        self._flagged = set(flagged)

    def flags(self, window: Window, anomaly: AnomalyResult) -> Mapping[str, bool]:
        return {ch: ch in self._flagged for ch in CHANNELS}


def _ts(i: int) -> str:
    return f"2026-08-10T00:00:{i:02d}.000Z"


def _stream(n: int, step: float = 1.0):
    return [
        build_telemetry(DEVICE, _ts(i), {ch: 10.0 + step * i for ch in CHANNELS}, i)
        for i in range(n)
    ]


def _pipeline(
    *,
    window_size: int,
    c=None,
    k=None,
    h=None,
    rule=None,
    policy=None,
) -> P2Pipeline:
    # Defaults built here (not in the signature) to avoid mutable/callable
    # default-argument pitfalls (ruff B008).
    return P2Pipeline(
        preprocessor=Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=window_size),
        detector=NullDetector(),
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(rule or StubPhysicsRule(violated=False)),
        c_provider=c or ConstantSignalProvider(1.0),
        k_provider=k or ConstantSignalProvider(1.0),
        h_provider=h or ConstantSignalProvider(1.0),
        flag_policy=policy or FixedFlagPolicy(),
    )


# --- full flow ---------------------------------------------------------------


def test_full_flow_single_window_shape():
    pipe = _pipeline(window_size=4)
    outcomes = pipe.process(_stream(4))
    assert len(outcomes) == 1
    (o,) = outcomes
    assert isinstance(o, WindowOutcome)
    assert o.window.size == 4
    assert isinstance(o.anomaly, AnomalyResult)
    # every channel represented in flags, trust, attribution
    for ch in CHANNELS:
        assert ch in o.channel_flags
        assert ch in o.trust
        assert ch in o.attribution


def test_clean_window_null_detector_yields_all_none_attribution():
    pipe = _pipeline(window_size=4)  # NullDetector + no flags + no violation
    (o,) = pipe.process(_stream(4))
    assert o.anomaly.flag is False and o.anomaly.severity == 0.0
    assert all(r.attribution is Attribution.none for r in o.attribution.values())


def test_flow_produces_attack_on_suspect_and_fault_elsewhere():
    # Architectural: flags come from the injected policy, suspect from the rule.
    pipe = _pipeline(
        window_size=4,
        rule=StubPhysicsRule(violated=True, suspect_channel="pressure", reason="r"),
        policy=FixedFlagPolicy(flagged=("pressure", "temperature")),
    )
    (o,) = pipe.process(_stream(4))
    assert o.attribution["pressure"].attribution is Attribution.attack
    assert o.attribution["temperature"].attribution is Attribution.fault
    assert o.attribution["gas"].attribution is Attribution.none


# --- multiple windows --------------------------------------------------------


def test_multiple_windows_count():
    pipe = _pipeline(window_size=3)
    outcomes = pipe.process(_stream(6))  # windows [0,3)..[3,6) => 4
    assert len(outcomes) == 4
    assert [o.window.start_index for o in outcomes] == [0, 1, 2, 3]


def test_trust_evolves_across_windows():
    # g=1 every window -> trust climbs monotonically as windows advance.
    pipe = _pipeline(window_size=3)  # constant providers c=k=h=1
    outcomes = pipe.process(_stream(6))
    series = [o.trust["current"].trust for o in outcomes]
    assert series == sorted(series)
    assert series[-1] >= series[0]


# --- independent channel trust ----------------------------------------------


def test_channel_trust_is_independent():
    # c=1 on pressure only; others c=0. k=h=0. pressure trust must diverge up.
    c = MappingSignalProvider({ch: (1.0 if ch == "pressure" else 0.0) for ch in CHANNELS})
    pipe = _pipeline(
        window_size=3,
        c=c,
        k=ConstantSignalProvider(0.0),
        h=ConstantSignalProvider(0.0),
    )
    outcomes = pipe.process(_stream(6))
    last = outcomes[-1].trust
    assert last["pressure"].trust > last["gas"].trust  # diverged, independent


# --- edges -------------------------------------------------------------------


def test_empty_stream_yields_no_outcomes():
    assert _pipeline(window_size=4).process([]) == []


def test_stream_shorter_than_window_yields_no_outcomes():
    assert _pipeline(window_size=30).process(_stream(5)) == []


def test_stub_flag_policy_satisfies_protocol():
    assert isinstance(FixedFlagPolicy(), ChannelFlagPolicy)


def test_channels_helper_matches_frozen_set():
    assert P2Pipeline.channels() == CHANNELS


# --- Provider wiring integration tests ---
# (Prove that real c/h/k providers are actually updated by the pipeline)


def test_pipeline_calls_record_window_on_c_provider():
    """Prove that pipeline calls c.record_window(window) before update_from_providers()."""
    from edge.trust.c_consistency import ConsistencyProvider

    # Create a real ConsistencyProvider
    c = ConsistencyProvider()

    # Create a simple training window
    pp = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=4)
    training_stream = _stream(4)
    training_windows = pp.process(training_stream)

    # Fit the provider
    c.fit(training_windows)

    # Before processing, c should be at initial 0.5
    assert c.evaluate("temperature") == 0.5

    # Create pipeline with real c provider
    pipe = _pipeline(window_size=4, c=c)

    # Process a stream
    _ = pipe.process(_stream(4))

    # After processing, c should have been updated (no longer 0.5)
    # It will be 1.0 or some value based on the test stream matching training
    temp_c = c.evaluate("temperature")
    assert temp_c != 0.5, "c provider was not updated by pipeline"
    assert 0.0 <= temp_c <= 1.0


def test_pipeline_calls_record_outcome_on_h_provider():
    """Prove that pipeline calls h.record_outcome(channel, was_healthy)."""
    from edge.trust.h_reliability import HReliabilityProvider

    h = HReliabilityProvider()

    # Before processing, h should be at initial 1.0
    assert h.evaluate("temperature") == 1.0

    # Create pipeline with real h provider and a flags policy that marks all channels unhealthy
    pipe = _pipeline(
        window_size=4,
        h=h,
        policy=FixedFlagPolicy(flagged=("temperature", "vibration"))  # Mark some unhealthy
    )

    # Process a stream (1 window)
    _ = pipe.process(_stream(4))

    # After processing with flags, h should have decayed for flagged channels
    temp_h = h.evaluate("temperature")
    assert temp_h < 1.0, "h provider was not updated by pipeline for flagged channel"
    assert temp_h > 0.0, "h should not go to zero after one unhealthy outcome"

    # Non-flagged channel should stay at 1.0
    pressure_h = h.evaluate("pressure")
    assert pressure_h == 1.0, "h should not decay for non-flagged channels"


def test_pipeline_calls_record_window_on_k_provider():
    """Prove that pipeline calls k.record_window(window) before update_from_providers()."""
    from edge.trust.k_correlation import CorrelationProvider

    k = CorrelationProvider()

    # Before processing, k should be at initial 0.5
    assert k.evaluate("current") == 0.5

    # Create pipeline with real k provider
    pipe = _pipeline(window_size=4, k=k)

    # Process a stream
    _ = pipe.process(_stream(4))

    # After processing, k should have been updated (no longer 0.5)
    # For the constant stream, both current and vibration rise together, so k=1.0
    current_k = k.evaluate("current")
    assert current_k != 0.5, "k provider was not updated by pipeline"
    assert 0.0 <= current_k <= 1.0


def test_pipeline_c_h_k_wiring_together():
    """Full integration: all three real providers wired together."""
    from edge.trust.c_consistency import ConsistencyProvider
    from edge.trust.h_reliability import HReliabilityProvider
    from edge.trust.k_correlation import CorrelationProvider

    c = ConsistencyProvider()
    h = HReliabilityProvider()
    k = CorrelationProvider()

    # Fit c on training data
    pp = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=4)
    training_windows = pp.process(_stream(4))
    c.fit(training_windows)

    # Create pipeline with real providers
    pipe = _pipeline(window_size=4, c=c, h=h, k=k)

    # Process stream
    outcomes = pipe.process(_stream(6))

    # Verify all three were updated
    assert c.evaluate("temperature") != 0.5, "c not updated"
    assert h.evaluate("temperature") == 1.0, "h should stay 1.0 when not flagged"
    assert k.evaluate("current") != 0.5, "k not updated"

    # Verify trust was computed (should use c, k, h values)
    assert len(outcomes) == 3  # 3 windows of size 4 from stream of 6
    for outcome in outcomes:
        assert len(outcome.trust) == 6  # 6 channels
        for ch in CHANNELS:
            trust = outcome.trust[ch].trust
            assert 0.0 <= trust <= 1.0, f"trust out of range for {ch}"
