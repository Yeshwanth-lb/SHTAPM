"""Tests for edge/eval/twin_training.py (P3 digital-twin training harness,
hardware-free, DIAGNOSTIC ONLY).

Proves the training/inference PLUMBING works (forward pass, loss
computation, gradient flow, weight updates) using ONLY the existing
D005/D008 simulator + Preprocessor. NOTHING here claims, or should be read
as claiming, meaningful reconstruction accuracy or real-world validation --
see edge/eval/twin_training.py's own module/function docstrings. All
numeric values below are TEST FIXTURES ONLY.

Skipped entirely when torch is unavailable -- same skip-pattern as
test_iforest.py for scikit-learn.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402
from app.schemas.contracts import CHANNELS  # noqa: E402

from edge.anomaly.preprocess import Preprocessor, Window  # noqa: E402
from edge.eval.twin_training import (  # noqa: E402
    PREPROC_FIXTURE,
    generate_clean_windows,
    make_training_examples,
    train,
)
from edge.models.lstm_twin import _LSTMTwinNet  # noqa: E402

SEED_FIXTURE = 1337
FRAME_COUNT_FIXTURE = 35  # -> 35-30+1 = 6 windows at step=1
HIDDEN_SIZE_FIXTURE = 4
EPOCHS_FIXTURE = 2
# ADAM_OPTIMIZER_FIXTURE: a diagnostic choice for these tests' own smoke
# training run only -- NOT an approved project optimizer specification.
LEARNING_RATE_FIXTURE = 0.01


def _clean_windows():
    preprocessor = Preprocessor(**PREPROC_FIXTURE)
    return generate_clean_windows(
        frame_count=FRAME_COUNT_FIXTURE, seed=SEED_FIXTURE, preprocessor=preprocessor
    )


def test_generate_clean_windows_uses_documented_preprocessing():
    windows = _clean_windows()
    assert len(windows) == FRAME_COUNT_FIXTURE - PREPROC_FIXTURE["window_size"] + 1
    assert windows[0].size == PREPROC_FIXTURE["window_size"]


def test_make_training_examples_target_matches_true_value():
    windows = _clean_windows()
    examples = make_training_examples(windows)
    assert len(examples) == len(windows) * len(CHANNELS)
    for input_tensor, target, channel in examples[:5]:
        assert isinstance(target, float)
        assert channel in CHANNELS
        assert input_tensor.shape == (1, PREPROC_FIXTURE["window_size"], 2 * len(CHANNELS))

    # Exact-value check: a bug reading the wrong timestep or wrong channel
    # would still satisfy the type/shape/membership checks above, so verify
    # the target against a specific, known, distinctive fixture value.
    distinctive_value = 0.123456
    window_size = PREPROC_FIXTURE["window_size"]
    features = {ch: tuple(0.5 for _ in range(window_size)) for ch in CHANNELS}
    features["temperature"] = tuple([0.5] * (window_size - 1) + [distinctive_value])
    distinctive_window = Window(start_index=0, end_index=window_size, features=features)

    distinctive_examples = make_training_examples([distinctive_window])
    temperature_targets = [
        target for _, target, channel in distinctive_examples if channel == "temperature"
    ]
    assert temperature_targets == [distinctive_value]

    # No other channel's example may pick up this value -- rules out a
    # wrong-channel read producing a false pass.
    other_targets = [
        target for _, target, channel in distinctive_examples if channel != "temperature"
    ]
    assert distinctive_value not in other_targets


def test_training_loop_is_mechanically_sound():
    """Smoke test only: proves the loop runs, loss is finite, and weights
    actually change. Makes NO claim about reconstruction quality."""
    windows = _clean_windows()
    examples = make_training_examples(windows)
    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    before = {name: param.clone() for name, param in network.state_dict().items()}

    # ADAM_OPTIMIZER_FIXTURE: diagnostic choice for this test only.
    ADAM_OPTIMIZER_FIXTURE = torch.optim.Adam(network.parameters(), lr=LEARNING_RATE_FIXTURE)
    loss_history = train(network, examples, epochs=EPOCHS_FIXTURE, optimizer=ADAM_OPTIMIZER_FIXTURE)

    assert len(loss_history) == EPOCHS_FIXTURE
    for loss_value in loss_history:
        assert loss_value == loss_value  # not NaN
        assert loss_value != float("inf")

    after = network.state_dict()
    changed = any(not torch.equal(before[name], after[name]) for name in before)
    assert changed


def test_train_requires_epochs_and_optimizer_with_no_default():
    sig = inspect.signature(train)
    assert sig.parameters["epochs"].default is inspect.Parameter.empty
    assert sig.parameters["optimizer"].default is inspect.Parameter.empty
