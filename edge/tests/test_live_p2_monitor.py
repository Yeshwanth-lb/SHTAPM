"""P0 gap-closure item 1 — LiveP2Monitor unit tests (edge/pipeline/monitor.py).

Builds the same real (non-stub) component composition edge/main.py uses —
NullDetector, unfitted SeverityThresholdFlagPolicy/TrendSignPhysicsRule,
CorrelationProvider/HReliabilityProvider (no fit needed), and a
ConsistencyProvider bootstrapped by the monitor itself — reconstructed
locally here (not by importing edge.main) to keep this test hardware-import
-free, matching this codebase's existing test convention.

FIT_WINDOW_COUNT=5 is this test file's own arbitrary fixture value (not a
project spec number — see edge/pipeline/monitor.py's docstring for why the
real value is a required, undefaulted config parameter). With the default
window_size=30 and step=1, the fit-buffer-size formula
(edge/pipeline/monitor.py) gives:

    fit_buffer_size = 30 + (5 - 1) * 1 = 34

i.e. the monitor stays silent (no outcome, no fit) for the first 33 frames,
fits + emits its first outcome on the 34th, then continues one outcome per
tick exactly as before this fix.
"""

from __future__ import annotations

import random

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.detector import NullDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline, WindowOutcome
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.pipeline.monitor import LiveP2Monitor
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

DEVICE = "pump-01"
VALUES = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.42,
}
FIT_WINDOW_COUNT = 5
WINDOW_SIZE = 30  # Preprocessor's own default
FIT_BUFFER_SIZE = WINDOW_SIZE + (FIT_WINDOW_COUNT - 1) * 1  # step=1 default -> 34


def _ts(i: int) -> str:
    minute, second = divmod(i, 60)
    hour, minute = divmod(minute, 60)
    return f"2026-09-05T{hour:02d}:{minute:02d}:{second:02d}.000Z"


class _CountingConsistencyProvider(ConsistencyProvider):
    """Spy on fit() call count without changing any behavior."""

    def __init__(self) -> None:
        super().__init__()
        self.fit_calls = 0

    def fit(self, windows):  # noqa: D102 (spy wrapper, behavior identical to base)
        self.fit_calls += 1
        super().fit(windows)


def _build_monitor(
    on_outcome=lambda outcome: None,
    fit_window_count=FIT_WINDOW_COUNT,
    on_raw_values=None,
):
    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0)
    c_provider = _CountingConsistencyProvider()
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
    monitor = LiveP2Monitor(
        preprocessor=preprocessor,
        pipeline=pipeline,
        c_provider=c_provider,
        fit_window_count=fit_window_count,
        on_outcome=on_outcome,
        on_raw_values=on_raw_values,
    )
    return monitor, c_provider


def _frame(seq: int):
    return build_telemetry(DEVICE, _ts(seq), VALUES, seq)


def _noisy_frame(seq: int, seed: int):
    rng = random.Random(seed + seq)
    values = {
        ch: v + rng.uniform(-0.01 * abs(v) - 1e-6, 0.01 * abs(v) + 1e-6) for ch, v in VALUES.items()
    }
    return build_telemetry(DEVICE, _ts(seq), values, seq)


# ---- construction validation ------------------------------------------------


def test_fit_window_count_must_be_positive():
    import pytest

    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0)
    for bad in (0, -1, -5):
        with pytest.raises(ValueError, match="fit_window_count must be > 0"):
            LiveP2Monitor(
                preprocessor=preprocessor,
                pipeline=object(),  # never reached; validation happens first
                c_provider=ConsistencyProvider(),
                fit_window_count=bad,
            )


# ---- warm-up phase -----------------------------------------------------------


def test_no_outcome_and_not_fitted_before_fit_buffer_full():
    outcomes: list[WindowOutcome] = []
    monitor, c_provider = _build_monitor(on_outcome=outcomes.append)

    for i in range(FIT_BUFFER_SIZE - 1):  # 33 frames — one short of the fit buffer
        monitor.on_frame(_frame(i))

    assert outcomes == []
    assert c_provider.fitted is False


def test_fit_buffer_full_fits_on_exactly_fit_window_count_windows_and_emits_one_outcome():
    outcomes: list[WindowOutcome] = []
    monitor, c_provider = _build_monitor(on_outcome=outcomes.append)

    for i in range(FIT_BUFFER_SIZE):  # 34 frames
        monitor.on_frame(_frame(i))

    assert c_provider.fitted is True
    assert c_provider.fit_calls == 1
    assert len(c_provider._train_rms_z_sorted["temperature"]) == FIT_WINDOW_COUNT
    assert len(outcomes) == 1  # the transition tick also emits the first real outcome


def test_c_provider_fit_exactly_once_across_many_ticks():
    outcomes: list[WindowOutcome] = []
    monitor, c_provider = _build_monitor(on_outcome=outcomes.append)

    total = FIT_BUFFER_SIZE + 15  # fill the fit buffer + 15 more sliding ticks
    for i in range(total):
        monitor.on_frame(_frame(i))

    assert c_provider.fit_calls == 1
    assert len(outcomes) == 16  # 1 at the fit/transition tick + 15 subsequent ticks


# ---- steady-state sliding behavior (preserved after the fix) ---------------


def test_sliding_window_content_advances_each_tick_after_warmup():
    """A one-off spike placed just before the seeded post-fit buffer's start
    must be visible in the transition outcome's window and gone the very
    next tick, proving the one-window-per-tick sliding behavior is preserved
    unchanged after the (now multi-window) warm-up phase."""
    outcomes: list[WindowOutcome] = []
    monitor, _c = _build_monitor(on_outcome=outcomes.append)

    # The post-fit buffer is seeded from the LAST window_size frames of the
    # fit buffer, i.e. frames[FIT_BUFFER_SIZE - WINDOW_SIZE : FIT_BUFFER_SIZE].
    # A spike at that exact first included index is present in the
    # transition outcome and evicted on the very next tick.
    spike_at = FIT_BUFFER_SIZE - WINDOW_SIZE  # = 4

    def frame(seq: int):
        values = dict(VALUES)
        if seq == spike_at:
            values["temperature"] = 500.0
        return build_telemetry(DEVICE, _ts(seq), values, seq)

    for i in range(FIT_BUFFER_SIZE + 2):
        monitor.on_frame(frame(i))

    assert len(outcomes) == 3  # transition tick + 2 more
    assert any(v != 0.0 for v in outcomes[0].window.features["temperature"])
    assert all(v == 0.0 for v in outcomes[1].window.features["temperature"])
    assert all(v == 0.0 for v in outcomes[2].window.features["temperature"])


def test_outcome_covers_every_channel_with_null_detector_never_flagging():
    outcomes: list[WindowOutcome] = []
    monitor, _c = _build_monitor(on_outcome=outcomes.append)

    for i in range(FIT_BUFFER_SIZE):
        monitor.on_frame(_frame(i))

    outcome = outcomes[0]
    assert outcome.anomaly.flag is False
    assert outcome.anomaly.severity == 0.0
    assert set(outcome.trust.keys()) == set(CHANNELS)
    assert set(outcome.attribution.keys()) == set(CHANNELS)
    assert all(a.attribution == Attribution.none for a in outcome.attribution.values())


# ---- regression: fix for the single-window-fit binary-collapse defect -----


def test_fitted_consistency_output_is_not_binary_with_multiple_fit_windows():
    """Regression test for the defect found and fixed in this change:
    fitting ConsistencyProvider on a single window made its empirical-CDF
    lookup degenerate (train_rms_z_sorted length 1), so `c` could only ever
    read 0.0 or 1.0 -- even on perfectly clean, in-distribution data. With
    FIT_WINDOW_COUNT=5 (fit-buffer covers 5 distinct windows), the lookup
    table has 5 entries and `c` must be able to take more than 2 distinct
    values across a run of genuinely-varying clean windows."""
    from edge.trust.engine import TrustReading

    outcomes: list[WindowOutcome] = []
    monitor, c_provider = _build_monitor(on_outcome=outcomes.append)

    total = FIT_BUFFER_SIZE + 30  # warm up, then 30 more genuinely-varying ticks
    for i in range(total):
        monitor.on_frame(_noisy_frame(i, seed=7))

    assert len(c_provider._train_rms_z_sorted["temperature"]) == FIT_WINDOW_COUNT  # sanity
    trust_readings: list[TrustReading] = [o.trust["temperature"] for o in outcomes]
    c_values = {round(r.g, 6) for r in trust_readings}  # g reflects c/k/h; k,h are constant here
    # k is constant (non-current/vibration channel -> always 1.0) and h moves
    # extremely slowly (GAMMA=0.95), so essentially all variation in g across
    # this short run comes from c -- distinguishing "more than 2 distinct g
    # values" is a direct, observable proxy for "c is not binary".
    assert len(c_values) > 2, f"expected more than 2 distinct g values, got {c_values}"


def test_monitor_never_isolates_or_actuates():
    """Monitoring-only: the monitor has no actuation/isolation capability at
    all -- there is no such method to call. This test documents that
    invariant by construction (no RelayController/SelfHealOrchestrator
    import anywhere in edge/pipeline/monitor.py)."""
    import edge.pipeline.monitor as monitor_module

    source = monitor_module.__file__
    with open(source, encoding="utf-8") as f:
        content = f.read()
    assert "RelayController" not in content
    assert "SelfHealOrchestrator" not in content
    assert "process_isolated_channels" not in content


# ---------------------------------------------------------------------------
# Raw-value plumbing (integration-readiness prep -- observe-only)
# ---------------------------------------------------------------------------


def _distinct_frame(seq: int):
    """Every channel gets its own distinct value, so a test can prove
    channel names/values are routed correctly and not accidentally
    swapped/shared."""
    values = {
        "temperature": 100.0 + seq,
        "vibration": 200.0 + seq,
        "pressure": 300.0 + seq,
        "humidity": 400.0 + seq,
        "gas": 500.0 + seq,
        "current": 600.0 + seq,
    }
    return build_telemetry(DEVICE, _ts(seq), values, seq)


def test_no_raw_values_emitted_before_fit_buffer_full():
    raw_calls = []
    monitor, _c = _build_monitor(on_raw_values=lambda outcome, raw: raw_calls.append(raw))

    for i in range(FIT_BUFFER_SIZE - 1):  # one short of a complete window
        monitor.on_frame(_frame(i))

    assert raw_calls == []


def test_raw_values_emitted_once_fit_buffer_is_full():
    raw_calls = []
    monitor, _c = _build_monitor(on_raw_values=lambda outcome, raw: raw_calls.append(raw))

    for i in range(FIT_BUFFER_SIZE):
        monitor.on_frame(_frame(i))

    assert len(raw_calls) == 1


def test_raw_values_correspond_to_the_exact_window_that_produced_the_outcome():
    """The raw values must come from the SAME window as the paired
    WindowOutcome -- proven here via the frame's own ts/sample_seq, which
    must match the last (most recent) frame fed into that window."""
    pairs = []
    monitor, _c = _build_monitor(on_raw_values=lambda outcome, raw: pairs.append((outcome, raw)))

    for i in range(FIT_BUFFER_SIZE + 2):
        monitor.on_frame(_distinct_frame(i))

    assert len(pairs) == 3
    # Ticks are fed at i = 0..FIT_BUFFER_SIZE+1; the window completing at
    # tick i's most recent frame has sample_seq == i.
    expected_seqs = [FIT_BUFFER_SIZE - 1, FIT_BUFFER_SIZE, FIT_BUFFER_SIZE + 1]
    for (_outcome, raw), expected_seq in zip(pairs, expected_seqs, strict=True):
        assert raw.sample_seq == expected_seq
        assert raw.ts == _ts(expected_seq)


def test_raw_values_channel_names_and_values_preserved_exactly():
    raw_calls = []
    monitor, _c = _build_monitor(on_raw_values=lambda outcome, raw: raw_calls.append(raw))

    for i in range(FIT_BUFFER_SIZE):
        monitor.on_frame(_distinct_frame(i))

    raw = raw_calls[0]
    assert set(raw.values.keys()) == set(CHANNELS)
    last_seq = FIT_BUFFER_SIZE - 1
    assert raw.values == {
        "temperature": 100.0 + last_seq,
        "vibration": 200.0 + last_seq,
        "pressure": 300.0 + last_seq,
        "humidity": 400.0 + last_seq,
        "gas": 500.0 + last_seq,
        "current": 600.0 + last_seq,
    }


def test_raw_values_are_not_normalized_or_reconstructed():
    """Raw values must be the actual sensor readings, not the [0,1]
    min-max-normalized Window.features the P2 pipeline uses internally."""
    raw_calls = []
    monitor, _c = _build_monitor(on_raw_values=lambda outcome, raw: raw_calls.append(raw))

    for i in range(FIT_BUFFER_SIZE):
        monitor.on_frame(_frame(i))  # constant VALUES, e.g. temperature=26.0

    assert raw_calls[0].values["temperature"] == 26.0  # NOT a normalized [0,1] value
    assert raw_calls[0].values["pressure"] == 1013.0


def test_on_raw_values_is_optional_and_defaults_to_none():
    """No on_raw_values passed -> byte-identical behavior to before this
    parameter existed (must not raise, must not require the argument)."""
    outcomes = []
    monitor, _c = _build_monitor(on_outcome=outcomes.append)  # on_raw_values omitted

    for i in range(FIT_BUFFER_SIZE + 1):
        monitor.on_frame(_frame(i))

    assert len(outcomes) == 2  # existing on_outcome behavior fully unaffected


def test_existing_on_outcome_behavior_unaffected_by_raw_values_hook():
    """Adding on_raw_values must not change what on_outcome receives, nor
    how many times it's called, nor in what order relative to itself."""
    outcomes_with_raw_hook = []
    monitor_a, _ = _build_monitor(
        on_outcome=outcomes_with_raw_hook.append,
        on_raw_values=lambda outcome, raw: None,
    )
    outcomes_without_raw_hook = []
    monitor_b, _ = _build_monitor(on_outcome=outcomes_without_raw_hook.append)

    for i in range(FIT_BUFFER_SIZE + 2):
        monitor_a.on_frame(_frame(i))
        monitor_b.on_frame(_frame(i))

    assert len(outcomes_with_raw_hook) == len(outcomes_without_raw_hook) == 3
    for with_hook, without_hook in zip(
        outcomes_with_raw_hook, outcomes_without_raw_hook, strict=True
    ):
        assert with_hook.window.features == without_hook.window.features
        assert with_hook.anomaly == without_hook.anomaly


def test_raw_values_hook_never_isolates_or_actuates():
    """Structural proof, mirroring test_monitor_never_isolates_or_actuates:
    RawChannelValues/on_raw_values introduce no new forbidden call."""
    import edge.pipeline.monitor as monitor_module

    with open(monitor_module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "RelayController" not in content
    assert "SelfHealOrchestrator" not in content
    assert "process_isolated_channels" not in content
    assert "TwinReconstructor" not in content
    assert "divergence_threshold" not in content
