"""Tests for edge/models/lstm_twin.py (P3 digital-twin, hardware-free
plumbing/ML-pipeline development ONLY).

No test here claims, or should be read as claiming, meaningful
reconstruction accuracy or real-world validation. hidden_size and every
other numeric value below are TEST FIXTURES ONLY, never project specs.

Skipped entirely when torch is unavailable -- same skip-pattern as
test_iforest.py for scikit-learn.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402
from app.schemas.contracts import CHANNELS, Attribution  # noqa: E402

from edge.anomaly.attribution import AttributionResult  # noqa: E402
from edge.anomaly.detector import AnomalyResult  # noqa: E402
from edge.anomaly.pipeline import WindowOutcome  # noqa: E402
from edge.anomaly.preprocess import Window  # noqa: E402
from edge.models.lstm_twin import (  # noqa: E402
    LSTMTwinReconstructor,
    _LSTMTwinNet,
    build_masked_input,
)
from edge.models.twin import TwinReconstructor  # noqa: E402
from edge.pipeline.cycle import process_isolated_channels  # noqa: E402
from edge.pipeline.divergence import DivergenceScorer  # noqa: E402
from edge.pipeline.self_heal import SelfHealOrchestrator  # noqa: E402
from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy  # noqa: E402
from edge.trust.beta import classify  # noqa: E402
from edge.trust.engine import TrustReading  # noqa: E402

HIDDEN_SIZE_FIXTURE = 4
# Integration-test-only fixtures: SelfHealOrchestrator/process_isolated_channels
# require SOME divergence_threshold/uncertainty_cap to be constructed. TEST
# FIXTURES ONLY -- not project specification values; U05 remains open.
DIVERGENCE_THRESHOLD_FIXTURE = 3.0
UNCERTAINTY_CAP_FIXTURE = 0.8


def _LINEAR_SCALING_FIXTURE(elapsed_fraction: float) -> float:
    """TEST FIXTURE ONLY -- not the approved D019 scaling formula."""
    return elapsed_fraction


def _window(values_by_channel: dict[str, float]) -> Window:
    """30-sample window; each named channel is constant across all 30
    samples (unnamed channels default to 0.0) -- simplest fixture shape
    sufficient for these plumbing tests."""
    features = {
        ch: tuple(float(values_by_channel.get(ch, 0.0)) for _ in range(30)) for ch in CHANNELS
    }
    return Window(start_index=0, end_index=30, features=features)


# ---------------------------------------------------------------------------
# build_masked_input
# ---------------------------------------------------------------------------


def test_build_masked_input_shape():
    window = _window({})
    tensor = build_masked_input(window, "temperature")
    assert tensor.shape == (1, 30, 2 * len(CHANNELS))


def test_build_masked_input_rejects_unknown_channel():
    window = _window({})
    with pytest.raises(ValueError):
        build_masked_input(window, "not_a_channel")


def test_masked_channel_column_is_zero():
    window = _window({"temperature": 0.7})
    tensor = build_masked_input(window, "temperature")
    temp_index = CHANNELS.index("temperature")
    assert torch.all(tensor[0, :, temp_index] == 0.0)


def test_indicator_is_correct_one_hot_repeated_every_timestep():
    window = _window({})
    tensor = build_masked_input(window, "vibration")
    vib_index = CHANNELS.index("vibration")
    indicator_slice = tensor[0, :, len(CHANNELS) :]  # (30, len(CHANNELS))
    expected = torch.zeros(len(CHANNELS))
    expected[vib_index] = 1.0
    assert torch.all(indicator_slice == expected.expand(30, -1))


def test_masked_channels_true_value_never_appears_in_input():
    """Core invariant: the masked channel's own raw value must never reach
    the twin's input tensor. A distinctive value on the masked channel must
    appear nowhere in the built tensor."""
    distinctive_value = 999.0
    window = _window({"gas": distinctive_value})
    tensor = build_masked_input(window, "gas")
    assert not torch.any(tensor == distinctive_value)


# ---------------------------------------------------------------------------
# _LSTMTwinNet / LSTMTwinReconstructor
# ---------------------------------------------------------------------------


def test_hidden_size_has_no_default_on_net_and_reconstructor():
    sig_net = inspect.signature(_LSTMTwinNet.__init__)
    assert sig_net.parameters["hidden_size"].default is inspect.Parameter.empty
    sig_reconstructor = inspect.signature(LSTMTwinReconstructor.__init__)
    assert sig_reconstructor.parameters["network"].default is inspect.Parameter.empty


def test_reconstruct_returns_finite_float():
    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    reconstructor = LSTMTwinReconstructor(network)
    window = _window({"temperature": 0.5})
    value = reconstructor.reconstruct(window, "temperature")
    assert isinstance(value, float)
    assert value == value  # not NaN
    assert value not in (float("inf"), float("-inf"))


def test_reconstruct_is_deterministic_in_eval_mode():
    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    reconstructor = LSTMTwinReconstructor(network)
    window = _window({"temperature": 0.5})
    first = reconstructor.reconstruct(window, "temperature")
    second = reconstructor.reconstruct(window, "temperature")
    assert first == second


def test_reconstructor_satisfies_twin_reconstructor_protocol():
    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    reconstructor = LSTMTwinReconstructor(network)
    assert isinstance(reconstructor, TwinReconstructor)


def test_save_and_from_checkpoint_round_trip(tmp_path):
    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    reconstructor = LSTMTwinReconstructor(network)
    window = _window({"temperature": 0.5})
    before = reconstructor.reconstruct(window, "temperature")

    checkpoint_path = tmp_path / "twin.pt"
    reconstructor.save(str(checkpoint_path))
    reloaded = LSTMTwinReconstructor.from_checkpoint(
        str(checkpoint_path), hidden_size=HIDDEN_SIZE_FIXTURE
    )
    after = reloaded.reconstruct(window, "temperature")

    assert before == after


# ---------------------------------------------------------------------------
# Integration: real LSTMTwinReconstructor through the P3 orchestration
# plumbing (SelfHealOrchestrator, process_isolated_channels). Proves the
# real twin conforms to the TwinReconstructor seam and actually flows
# through the existing orchestration -- NOT that it reconstructs anything
# meaningful (hidden_size is a tiny, untrained-or-arbitrarily-initialized
# fixture network; no accuracy claim is made or tested here).
# ---------------------------------------------------------------------------


def _make_orchestrator_with_real_twin():
    """A real SelfHealOrchestrator wired to a real (untrained)
    LSTMTwinReconstructor -- integration-plumbing tests only."""
    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    twin = LSTMTwinReconstructor(network)
    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=_LINEAR_SCALING_FIXTURE)
    calls = {"n": 0}

    def safe_stop():
        calls["n"] += 1

    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
        uncertainty_cap=UNCERTAINTY_CAP_FIXTURE,
        safe_stop=safe_stop,
    )
    return orchestrator, calls


def test_real_lstm_twin_flows_through_self_heal_orchestrator():
    """The real LSTMTwinReconstructor (not a fixture stub) must produce a
    well-formed SelfHealOutcome when driven directly through the real
    SelfHealOrchestrator."""
    orchestrator, _calls = _make_orchestrator_with_real_twin()
    window = _window({"temperature": 0.5})

    outcome = orchestrator.process_isolated_channel("temperature", window, raw_value=0.5, trust=0.2)

    assert isinstance(outcome.reconstructed_value, float)
    assert outcome.divergence is not None
    assert outcome.uncertainty is not None
    assert isinstance(outcome.substituted, bool)
    assert isinstance(outcome.escalated, bool)


def test_real_lstm_twin_flows_through_process_isolated_channels():
    """The full P2->P3 chain (WindowOutcome -> process_isolated_channels ->
    SelfHealOrchestrator) with a real LSTMTwinReconstructor must produce a
    well-formed SelfHealOutcome."""
    orchestrator, _calls = _make_orchestrator_with_real_twin()
    window = _window({"temperature": 0.5})

    trust = {ch: TrustReading(channel=ch, g=0.0, trust=0.9, band=classify(0.9)) for ch in CHANNELS}
    trust["temperature"] = TrustReading(channel="temperature", g=0.0, trust=0.2, band=classify(0.2))
    window_outcome = WindowOutcome(
        window=window,
        anomaly=AnomalyResult(flag=False, severity=0.0),
        channel_flags={ch: False for ch in CHANNELS},
        trust=trust,
        attribution={ch: AttributionResult(ch, Attribution.none, "") for ch in CHANNELS},
    )

    results = process_isolated_channels(
        window_outcome,
        isolated_channels={"temperature"},
        raw_values={"temperature": 0.5},
        orchestrator=orchestrator,
    )

    assert set(results.keys()) == {"temperature"}
    result = results["temperature"]
    assert isinstance(result.reconstructed_value, float)
    assert result.divergence is not None
    assert result.uncertainty is not None
    assert isinstance(result.substituted, bool)
    assert isinstance(result.escalated, bool)
