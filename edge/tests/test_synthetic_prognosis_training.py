"""Tests for edge/eval/synthetic_prognosis_training.py (diagnostic-only
synthetic prognosis training harness). Hardware-free plumbing verification
ONLY -- no test here claims meaningful prognosis accuracy; see the
module's own docstring.

Skipped entirely when torch is unavailable -- same skip-pattern as
edge/tests/test_lstm_prognosis.py.
"""

from __future__ import annotations

import copy

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402
from app.schemas.contracts import CHANNELS, HealthState  # noqa: E402

from edge.anomaly.preprocess import Preprocessor  # noqa: E402
from edge.eval.synthetic_prognosis_training import (  # noqa: E402
    HEALTH_LABEL_SOURCE,
    PROGNOSIS_DATA_SOURCE,
    SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    SYNTHETIC_HEALTH_WARNING_THRESHOLD,
    SyntheticWindowExample,
    classify_synthetic_health,
    make_training_examples,
    train,
)
from edge.models.degradation_generator import (  # noqa: E402
    ChannelDegradationConfig,
    SyntheticDegradationGenerator,
)
from edge.models.lstm_prognosis import _LSTMPrognosisNet  # noqa: E402
from edge.trust.beta import classify  # noqa: E402
from edge.trust.engine import TrustReading  # noqa: E402

HIDDEN_SIZE_FIXTURE = 4
LENGTH_FIXTURE = 40
WINDOW_SIZE_FIXTURE = 30


def _preprocessor() -> Preprocessor:
    return Preprocessor(
        median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW_SIZE_FIXTURE, step=1
    )


def _trust() -> dict[str, TrustReading]:
    return {ch: TrustReading(channel=ch, g=0.0, trust=1.0, band=classify(1.0)) for ch in CHANNELS}


def _generator(**overrides) -> SyntheticDegradationGenerator:
    config = {
        "length": LENGTH_FIXTURE,
        "start_health": 1.0,
        "end_health": 0.0,
        "seed": 1337,
        "channels": {
            "vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2),
        },
    }
    config.update(overrides)
    return SyntheticDegradationGenerator(**config)


def _timestamps(n: int) -> list[str]:
    return [f"2026-08-10T00:{i // 60:02d}:{i % 60:02d}.000Z" for i in range(n)]


def _examples(**generator_overrides) -> list[SyntheticWindowExample]:
    generator = _generator(**generator_overrides)
    return make_training_examples(
        generator,
        _timestamps(generator.length),
        _preprocessor(),
        _trust(),
        warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    )


# ---------------------------------------------------------------------------
# HealthState classification-label mapping
# ---------------------------------------------------------------------------


def test_healthy_fraction_classifies_as_healthy():
    fraction = SYNTHETIC_HEALTH_WARNING_THRESHOLD + 0.5 * (1.0 - SYNTHETIC_HEALTH_WARNING_THRESHOLD)
    result = classify_synthetic_health(
        fraction,
        warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    )
    assert result == HealthState.healthy


def test_warning_fraction_classifies_as_warning():
    midpoint = (SYNTHETIC_HEALTH_WARNING_THRESHOLD + SYNTHETIC_HEALTH_CRITICAL_THRESHOLD) / 2
    result = classify_synthetic_health(
        midpoint,
        warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    )
    assert result == HealthState.warning


def test_critical_fraction_classifies_as_critical():
    fraction = SYNTHETIC_HEALTH_CRITICAL_THRESHOLD / 2
    result = classify_synthetic_health(
        fraction,
        warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    )
    assert result == HealthState.critical


def test_exact_boundary_values_use_inclusive_lower_bound():
    # health_fraction == warning_threshold exactly -> NOT > warning_threshold -> Warning.
    at_warning = classify_synthetic_health(
        SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    )
    assert at_warning == HealthState.warning
    # health_fraction == critical_threshold exactly -> NOT > critical_threshold -> Critical.
    at_critical = classify_synthetic_health(
        SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
        warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    )
    assert at_critical == HealthState.critical


def test_invalid_threshold_ordering_raises():
    with pytest.raises(ValueError):
        classify_synthetic_health(0.5, warning_threshold=0.1, critical_threshold=0.2)


def test_thresholds_require_explicit_arguments_not_defaulted():
    with pytest.raises(TypeError):
        classify_synthetic_health(0.5)  # type: ignore[call-arg]


def test_synthetic_thresholds_are_distinct_from_d026_pronostia_values():
    """D026's PRONOSTIA-specific proportions are 0.20/0.05 -- the synthetic
    fixtures must never numerically coincide with them, so the two can
    never be visually conflated (see module docstring)."""
    assert SYNTHETIC_HEALTH_WARNING_THRESHOLD != 0.20
    assert SYNTHETIC_HEALTH_CRITICAL_THRESHOLD != 0.05


# ---------------------------------------------------------------------------
# Example construction
# ---------------------------------------------------------------------------


def test_make_training_examples_produces_expected_count():
    examples = _examples()
    expected_count = LENGTH_FIXTURE - WINDOW_SIZE_FIXTURE + 1  # step=1
    assert len(examples) == expected_count


def test_example_input_tensor_has_expected_shape():
    tensor = _examples()[0].input_tensor
    assert tensor.shape == (1, WINDOW_SIZE_FIXTURE, 11)  # unchanged 11-column contract


def test_example_health_fraction_matches_generator_trajectory_at_final_tick():
    generator = _generator()
    trajectory = generator.generate(_timestamps(LENGTH_FIXTURE))
    examples = make_training_examples(
        generator,
        _timestamps(LENGTH_FIXTURE),
        _preprocessor(),
        _trust(),
        warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
    )

    assert examples[0].health_fraction == pytest.approx(trajectory.health[WINDOW_SIZE_FIXTURE - 1])
    assert examples[-1].health_fraction == pytest.approx(trajectory.health[-1])


def test_example_health_state_matches_classify_synthetic_health():
    examples = _examples()
    for example in examples:
        expected = classify_synthetic_health(
            example.health_fraction,
            warning_threshold=SYNTHETIC_HEALTH_WARNING_THRESHOLD,
            critical_threshold=SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
        )
        assert example.health_state == expected


def test_health_fraction_is_monotonically_non_increasing_across_examples():
    fractions = [ex.health_fraction for ex in _examples()]
    for earlier, later in zip(fractions, fractions[1:], strict=False):
        assert later <= earlier


def test_all_three_health_states_appear_across_a_full_trajectory():
    """A trajectory spanning start_health=1.0 -> end_health=0.0 with these
    thresholds must produce at least one example of each class -- proving
    the classification labels aren't degenerate (e.g. always Healthy)."""
    examples = _examples(length=200)
    states = {ex.health_state for ex in examples}
    assert states == {HealthState.healthy, HealthState.warning, HealthState.critical}


# ---------------------------------------------------------------------------
# Training -- both heads
# ---------------------------------------------------------------------------


def test_train_runs_and_returns_one_loss_value_per_epoch():
    examples = _examples()
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    optimizer = torch.optim.Adam(network.parameters(), lr=0.01)

    loss_history = train(network, examples, epochs=3, optimizer=optimizer)

    assert len(loss_history) == 3
    assert all(isinstance(loss, float) and loss == loss for loss in loss_history)  # no NaN


def test_classification_head_parameters_change_after_training():
    """Proves the classification head is genuinely included in training
    (not just present but untouched) -- its weights must differ from their
    pre-training values after a real optimizer step."""
    examples = _examples(length=200)  # needs >=2 classes present to get a nonzero class loss
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    before = copy.deepcopy(network._health_head.weight.detach())
    optimizer = torch.optim.Adam(network.parameters(), lr=0.1)

    train(network, examples, epochs=1, optimizer=optimizer)

    after = network._health_head.weight.detach()
    assert not torch.equal(before, after)


def test_classification_head_receives_nonzero_gradient():
    examples = _examples(length=200)
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    optimizer = torch.optim.Adam(network.parameters(), lr=0.01)

    train(network, examples[:5], epochs=1, optimizer=optimizer)

    # After at least one backward pass, the classification head must have
    # accumulated a gradient at some point (checked via a fresh manual pass,
    # since train() zeroes grads each step).
    network.train()
    optimizer.zero_grad()
    health_logits, eta = network(examples[0].input_tensor)
    class_target = torch.tensor([0])
    reg_target = torch.tensor([[0.5]])
    loss = torch.nn.functional.cross_entropy(health_logits, class_target)
    loss = loss + torch.nn.functional.mse_loss(eta, reg_target)
    loss.backward()
    assert network._health_head.weight.grad is not None
    assert torch.any(network._health_head.weight.grad != 0)


def test_train_rejects_zero_epochs():
    examples = [
        SyntheticWindowExample(
            input_tensor=torch.zeros(1, 30, 11),
            health_fraction=0.5,
            health_state=HealthState.warning,
        )
    ]
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    optimizer = torch.optim.Adam(network.parameters(), lr=0.01)
    with pytest.raises(ValueError, match="epochs"):
        train(network, examples, epochs=0, optimizer=optimizer)


def test_train_rejects_empty_examples():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    optimizer = torch.optim.Adam(network.parameters(), lr=0.01)
    with pytest.raises(ValueError, match="empty"):
        train(network, [], epochs=1, optimizer=optimizer)


def test_train_leaves_network_in_eval_mode():
    examples = _examples()
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    optimizer = torch.optim.Adam(network.parameters(), lr=0.01)

    train(network, examples, epochs=1, optimizer=optimizer)

    assert network.training is False


# ---------------------------------------------------------------------------
# Separation from the PRONOSTIA training path + labeling
# ---------------------------------------------------------------------------


def test_data_source_label_is_synthetic():
    assert PROGNOSIS_DATA_SOURCE == "synthetic"


def test_health_label_source_constant():
    assert HEALTH_LABEL_SOURCE == "synthetic_policy_fixture"


def test_module_does_not_import_pronostia_training_or_reuse_d026_constants():
    import edge.eval.synthetic_prognosis_training as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "pronostia_prognosis_training import" not in content
    assert "pronostia_prep import" not in content
    assert "WARNING_PROPORTION_D026" not in content
    assert "CRITICAL_PROPORTION_D026" not in content


def test_module_has_no_hardware_or_network_imports():
    import edge.eval.synthetic_prognosis_training as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RPi", "gpiozero", "paho"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()
