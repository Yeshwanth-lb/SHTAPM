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
from app.schemas.contracts import CHANNELS  # noqa: E402

from edge.anomaly.preprocess import Window  # noqa: E402
from edge.models.lstm_twin import (  # noqa: E402
    LSTMTwinReconstructor,
    _LSTMTwinNet,
    build_masked_input,
)
from edge.models.twin import TwinReconstructor  # noqa: E402

HIDDEN_SIZE_FIXTURE = 4


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
