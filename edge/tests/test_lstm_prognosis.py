"""Tests for edge/models/lstm_prognosis.py (P3 prognosis skeleton, hardware-
free ARCHITECTURE/PLUMBING development ONLY).

No test here claims, or should be read as claiming, meaningful health-state
classification, ETA quality, or real-world validation of FR-M1/M2.
hidden_size and every other numeric value below are TEST FIXTURES ONLY,
never project specs. There is no training test, no dataset, and no
accuracy/classification/ETA-quality assertion anywhere in this file --
none of that exists yet (see edge/models/lstm_prognosis.py's module
docstring and DECISIONS.md D017).

No Protocol-conformance test: edge/models/lstm_prognosis.py deliberately
does not introduce a PrognosisPredictor Protocol (no P3 code currently
consumes one -- see that module's docstring).

Skipped entirely when torch is unavailable -- same skip-pattern as
test_lstm_twin.py.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402
from app.schemas.contracts import CHANNELS, HealthState  # noqa: E402

from edge.anomaly.preprocess import Window  # noqa: E402
from edge.models.lstm_prognosis import (  # noqa: E402
    LSTMPrognosisPredictor,
    _LSTMPrognosisNet,
    build_trust_weighted_input,
)
from edge.trust.beta import classify  # noqa: E402
from edge.trust.engine import TrustReading  # noqa: E402

HIDDEN_SIZE_FIXTURE = 4


def _window(values_by_channel: dict[str, float]) -> Window:
    """30-sample window; each named channel is constant across all 30
    samples (unnamed channels default to 0.0) -- same fixture shape as
    test_lstm_twin.py."""
    features = {
        ch: tuple(float(values_by_channel.get(ch, 0.0)) for _ in range(30)) for ch in CHANNELS
    }
    return Window(start_index=0, end_index=30, features=features)


def _trust(overrides: dict[str, float]) -> dict[str, TrustReading]:
    """All channels default to trust=1.0 unless overridden."""
    return {
        ch: TrustReading(
            channel=ch, g=0.0, trust=overrides.get(ch, 1.0), band=classify(overrides.get(ch, 1.0))
        )
        for ch in CHANNELS
    }


# ---------------------------------------------------------------------------
# build_trust_weighted_input
# ---------------------------------------------------------------------------


def test_build_trust_weighted_input_shape():
    window = _window({})
    tensor = build_trust_weighted_input(window, _trust({}))
    assert tensor.shape == (1, 30, len(CHANNELS))


def test_trust_weighting_scales_values():
    window = _window({"temperature": 10.0})
    tensor = build_trust_weighted_input(window, _trust({"temperature": 0.5}))
    temp_index = CHANNELS.index("temperature")
    assert torch.allclose(tensor[0, :, temp_index], torch.full((30,), 5.0))


def test_trust_zero_removes_channel_contribution():
    """Core invariant: trust=0 for a channel must zero every one of that
    channel's values in the built tensor, regardless of the channel's raw
    reading."""
    window = _window({"vibration": 999.0})
    tensor = build_trust_weighted_input(window, _trust({"vibration": 0.0}))
    vib_index = CHANNELS.index("vibration")
    assert torch.all(tensor[0, :, vib_index] == 0.0)


def test_build_trust_weighted_input_raises_on_missing_trust_channel():
    window = _window({})
    trust = _trust({})
    del trust["gas"]
    with pytest.raises(ValueError):
        build_trust_weighted_input(window, trust)


# ---------------------------------------------------------------------------
# _LSTMPrognosisNet / LSTMPrognosisPredictor
# ---------------------------------------------------------------------------


def test_hidden_size_has_no_default_on_net_and_predictor():
    sig_net = inspect.signature(_LSTMPrognosisNet.__init__)
    assert sig_net.parameters["hidden_size"].default is inspect.Parameter.empty
    sig_predictor = inspect.signature(LSTMPrognosisPredictor.__init__)
    assert sig_predictor.parameters["network"].default is inspect.Parameter.empty


def test_network_forward_output_shapes():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    window = _window({"temperature": 0.5})
    tensor = build_trust_weighted_input(window, _trust({}))
    health_logits, eta = network(tensor)
    assert health_logits.shape == (1, 3)
    assert eta.shape == (1, 1)


def test_predict_returns_valid_health_state_and_finite_eta():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    predictor = LSTMPrognosisPredictor(network)
    window = _window({"temperature": 0.5})
    health, eta = predictor.predict(window, _trust({}))
    assert isinstance(health, HealthState)
    assert isinstance(eta, float)
    assert eta == eta  # not NaN
    assert eta not in (float("inf"), float("-inf"))


def test_predict_is_deterministic_in_eval_mode():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    predictor = LSTMPrognosisPredictor(network)
    window = _window({"temperature": 0.5})
    trust = _trust({})
    first = predictor.predict(window, trust)
    second = predictor.predict(window, trust)
    assert first == second


def test_save_and_from_checkpoint_round_trip(tmp_path):
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    predictor = LSTMPrognosisPredictor(network)
    window = _window({"temperature": 0.5})
    trust = _trust({})
    before = predictor.predict(window, trust)

    checkpoint_path = tmp_path / "prognosis.pt"
    predictor.save(str(checkpoint_path))
    reloaded = LSTMPrognosisPredictor.from_checkpoint(
        str(checkpoint_path), hidden_size=HIDDEN_SIZE_FIXTURE
    )
    after = reloaded.predict(window, trust)

    assert before == after
