"""Tests for edge/eval/pronostia_prognosis_training.py (P3 PRONOSTIA
prognosis training harness: sliding-window examples, LOBO cross-
validation, multi-task loss, evaluation metrics).

Uses small SYNTHETIC PronostiaRunSequence fixtures only -- never the real
~1.1GB downloaded dataset, and never Validation_Set/Full_Test_Set or any
test-split bearing. No test here claims, or should be read as claiming,
meaningful trained accuracy -- see the module's own docstring.
"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402
from app.schemas.contracts import CHANNELS, HealthState  # noqa: E402

from edge.eval.pronostia_prep import PronostiaRunSequence  # noqa: E402
from edge.eval.pronostia_prognosis_targets import (  # noqa: E402
    TRAINING_BEARINGS_D025,
    compute_prognosis_targets,
)
from edge.eval.pronostia_prognosis_training import (  # noqa: E402
    EvaluationMetrics,
    WindowExample,
    class_weights,
    compute_channel_stats,
    evaluate,
    leave_one_bearing_out_splits,
    make_window_examples,
    normalize_examples,
    run_leave_one_bearing_out,
    train,
)
from edge.models.lstm_prognosis import _HEALTH_STATE_ORDER, _LSTMPrognosisNet  # noqa: E402
from edge.trust.beta import classify  # noqa: E402
from edge.trust.engine import TrustReading  # noqa: E402

TRAIN_BEARING_IDS = sorted(TRAINING_BEARINGS_D025)  # deterministic order for tests


def _sequence(n: int, bearing_id: str = "Bearing1_1") -> PronostiaRunSequence:
    return PronostiaRunSequence(
        bearing_id=bearing_id,
        operating_condition=1,
        split="training",
        timestamps=tuple((0, 0, i) for i in range(n)),
        temperature=tuple(20.0 + i for i in range(n)),
        vibration=tuple(float(i % 5) for i in range(n)),
        vibration_observed=tuple(1.0 for _ in range(n)),
    )


def _trust() -> dict[str, TrustReading]:
    return {ch: TrustReading(channel=ch, g=0.0, trust=1.0, band=classify(1.0)) for ch in CHANNELS}


def _optimizer_factory(params) -> torch.optim.Optimizer:
    return torch.optim.Adam(params, lr=0.01)


# ---------------------------------------------------------------------------
# make_window_examples
# ---------------------------------------------------------------------------


def test_window_count_matches_n_minus_window_size_plus_one():
    seq = _sequence(40)
    examples = make_window_examples(seq, _trust(), window_size=30, stride=1)
    assert len(examples) == 40 - 30 + 1  # 11


def test_window_count_with_stride():
    seq = _sequence(40)
    examples = make_window_examples(seq, _trust(), window_size=30, stride=5)
    # starts: 0, 5 -> 2 windows (0+30=30<=40, 5+30=35<=40, 10+30=40<=40, 15+30=45>40)
    assert len(examples) == 3


def test_input_tensor_shape_per_window():
    seq = _sequence(35)
    examples = make_window_examples(seq, _trust(), window_size=30, stride=1)
    for ex in examples:
        assert ex.input_tensor.shape == (1, 30, 11)


def test_empty_list_when_sequence_shorter_than_window():
    seq = _sequence(10)
    examples = make_window_examples(seq, _trust(), window_size=30, stride=1)
    assert examples == []


def test_target_matches_final_timestep_not_first_or_arbitrary():
    """Core semantic contract: the target for window [t, t+W-1] is the
    target AT t+W-1, verified directly against compute_prognosis_targets
    on the same sequence."""
    seq = _sequence(35)
    targets = compute_prognosis_targets(seq)
    examples = make_window_examples(seq, _trust(), window_size=30, stride=1)

    # First window: [0, 29] -> final timestep index 29.
    assert examples[0].rul_seconds == targets.rul_seconds[29]
    assert examples[0].health_state == targets.health_state[29]

    # Last window: [5, 34] -> final timestep index 34.
    assert examples[-1].rul_seconds == targets.rul_seconds[34]
    assert examples[-1].health_state == targets.health_state[34]


def test_bearing_lifetime_matches_n_minus_1():
    seq = _sequence(35)
    examples = make_window_examples(seq, _trust(), window_size=30, stride=1)
    for ex in examples:
        assert ex.bearing_lifetime == 34.0  # N-1 = 35-1


def test_non_training_bearing_id_rejected():
    """Validation is inherited from compute_prognosis_targets -- no
    duplicated bearing-id check in this module."""
    seq = _sequence(35, bearing_id="Bearing1_4")
    with pytest.raises(ValueError, match="training bearings"):
        make_window_examples(seq, _trust(), window_size=30, stride=1)


def test_window_size_must_be_positive():
    seq = _sequence(35)
    with pytest.raises(ValueError, match="window_size"):
        make_window_examples(seq, _trust(), window_size=0, stride=1)


def test_stride_must_be_positive():
    seq = _sequence(35)
    with pytest.raises(ValueError, match="stride"):
        make_window_examples(seq, _trust(), window_size=30, stride=0)


# ---------------------------------------------------------------------------
# class_weights
# ---------------------------------------------------------------------------


def _examples(n: int = 35, bearing_id: str = "Bearing1_1") -> list[WindowExample]:
    return make_window_examples(_sequence(n, bearing_id), _trust(), window_size=30, stride=1)


def test_class_weights_length_matches_health_state_order():
    weights = class_weights(_examples())
    assert weights.shape == (len(_HEALTH_STATE_ORDER),)


def test_class_weights_zero_for_unrepresented_class():
    """A batch containing only Healthy examples must give Warning/Critical
    weight 0.0, not a division-by-zero error."""
    all_examples = _examples(n=101)
    healthy_only = [ex for ex in all_examples if ex.health_state == HealthState.healthy]
    assert healthy_only  # sanity: the fixture does produce Healthy examples
    weights = class_weights(healthy_only)
    healthy_index = _HEALTH_STATE_ORDER.index(HealthState.healthy)
    for i in range(len(_HEALTH_STATE_ORDER)):
        if i == healthy_index:
            assert weights[i].item() > 0.0
        else:
            assert weights[i].item() == 0.0


def test_class_weights_higher_for_rarer_class():
    """Inverse-frequency property: a class with fewer examples must get a
    strictly larger weight than a class with more examples (both present)."""
    # n=101 -> total_lifetime=100, gives all three HealthState classes.
    examples = _examples(n=101)
    weights = class_weights(examples)
    counts = [0, 0, 0]
    for ex in examples:
        counts[_HEALTH_STATE_ORDER.index(ex.health_state)] += 1
    # healthy (index 0) is the majority class here; critical (index 2) the rarest.
    assert counts[0] > counts[2] > 0
    assert weights[2].item() > weights[0].item()


def test_class_weights_rejects_empty_examples():
    with pytest.raises(ValueError, match="empty"):
        class_weights([])


def test_class_weights_computed_only_from_given_examples():
    """Weights must depend only on the passed-in list -- calling it on a
    different bearing's examples must not be influenced by any prior call
    (no hidden shared/global state)."""
    weights_short = class_weights(_examples(n=31))
    weights_long = class_weights(_examples(n=101))
    weights_short_again = class_weights(_examples(n=31))
    assert torch.equal(weights_short, weights_short_again)
    assert not torch.equal(weights_short, weights_long)


# ---------------------------------------------------------------------------
# compute_channel_stats / normalize_examples
# ---------------------------------------------------------------------------


def test_compute_channel_stats_shape():
    mean, std = compute_channel_stats(_examples())
    assert mean.shape == (6,)
    assert std.shape == (6,)


def test_compute_channel_stats_zero_variance_channel_gets_std_one():
    """pressure/humidity/gas/current are always 0.0 in the fixture (no
    PRONOSTIA source, D024) -- their std must be forced to 1.0, not 0.0,
    so normalizing them is a no-op rather than a division by zero."""
    mean, std = compute_channel_stats(_examples())
    for idx, name in enumerate(("pressure", "humidity", "gas", "current"), start=2):
        assert mean[idx].item() == pytest.approx(0.0), name
        assert std[idx].item() == pytest.approx(1.0), name


def test_compute_channel_stats_nonzero_variance_channel():
    """temperature increases linearly in the fixture -- must have a
    nonzero, non-degenerate std (not forced to 1.0)."""
    mean, std = compute_channel_stats(_examples(n=101))
    temp_idx = 0
    assert std[temp_idx].item() > 0.0
    assert std[temp_idx].item() != 1.0


def test_compute_channel_stats_rejects_empty_examples():
    with pytest.raises(ValueError, match="empty"):
        compute_channel_stats([])


def test_normalize_examples_leaves_availability_columns_unchanged():
    examples = _examples()
    mean, std = compute_channel_stats(examples)
    normalized = normalize_examples(examples, mean, std)
    for original, norm in zip(examples, normalized, strict=True):
        # Columns 6-10 are the D022/D024 availability indicators.
        assert torch.equal(original.input_tensor[:, :, 6:], norm.input_tensor[:, :, 6:])


def test_normalize_examples_produces_approximately_zero_mean_on_fit_data():
    """Normalizing the SAME examples used to fit mean/std must center the
    non-degenerate (temperature) channel near 0 with unit-ish spread."""
    examples = _examples(n=101)
    mean, std = compute_channel_stats(examples)
    normalized = normalize_examples(examples, mean, std)
    all_temp_values = torch.cat([ex.input_tensor[:, :, 0] for ex in normalized])
    assert all_temp_values.mean().item() == pytest.approx(0.0, abs=1e-4)


def test_normalize_examples_does_not_mutate_original():
    examples = _examples()
    original_tensor = examples[0].input_tensor.clone()
    mean, std = compute_channel_stats(examples)
    normalize_examples(examples, mean, std)
    assert torch.equal(examples[0].input_tensor, original_tensor)


def test_normalize_examples_zero_variance_channel_stays_finite_not_nan():
    examples = _examples()
    mean, std = compute_channel_stats(examples)
    normalized = normalize_examples(examples, mean, std)
    pressure_values = normalized[0].input_tensor[:, :, 2]
    assert bool(torch.isfinite(pressure_values).all())


def test_normalize_examples_preserves_non_tensor_fields():
    examples = _examples()
    mean, std = compute_channel_stats(examples)
    normalized = normalize_examples(examples, mean, std)
    for original, norm in zip(examples, normalized, strict=True):
        assert norm.health_state == original.health_state
        assert norm.rul_seconds == original.rul_seconds
        assert norm.bearing_lifetime == original.bearing_lifetime


# ---------------------------------------------------------------------------
# train
# ---------------------------------------------------------------------------


def test_train_runs_and_returns_one_loss_per_epoch():
    network = _LSTMPrognosisNet(hidden_size=4)
    optimizer = _optimizer_factory(network.parameters())
    loss_history = train(network, _examples(), epochs=3, optimizer=optimizer, batch_size=2)
    assert len(loss_history) == 3
    assert all(torch.isfinite(torch.tensor(loss)) for loss in loss_history)


def test_train_updates_weights():
    network = _LSTMPrognosisNet(hidden_size=4)
    before = [p.clone() for p in network.parameters()]
    optimizer = _optimizer_factory(network.parameters())
    train(network, _examples(), epochs=2, optimizer=optimizer, batch_size=2)
    after = list(network.parameters())
    assert any(not torch.equal(b, a) for b, a in zip(before, after, strict=True))


def test_train_leaves_network_in_eval_mode():
    network = _LSTMPrognosisNet(hidden_size=4)
    optimizer = _optimizer_factory(network.parameters())
    train(network, _examples(), epochs=1, optimizer=optimizer, batch_size=2)
    assert network.training is False


def test_train_rejects_empty_examples():
    network = _LSTMPrognosisNet(hidden_size=4)
    optimizer = _optimizer_factory(network.parameters())
    with pytest.raises(ValueError, match="empty"):
        train(network, [], epochs=1, optimizer=optimizer, batch_size=2)


def test_train_rejects_zero_epochs():
    network = _LSTMPrognosisNet(hidden_size=4)
    optimizer = _optimizer_factory(network.parameters())
    with pytest.raises(ValueError, match="epochs"):
        train(network, _examples(), epochs=0, optimizer=optimizer, batch_size=2)


def test_train_rejects_zero_batch_size():
    network = _LSTMPrognosisNet(hidden_size=4)
    optimizer = _optimizer_factory(network.parameters())
    with pytest.raises(ValueError, match="batch_size"):
        train(network, _examples(), epochs=1, optimizer=optimizer, batch_size=0)


def test_train_handles_batch_size_larger_than_example_count():
    network = _LSTMPrognosisNet(hidden_size=4)
    optimizer = _optimizer_factory(network.parameters())
    examples = _examples(n=32)  # 3 windows
    loss_history = train(network, examples, epochs=1, optimizer=optimizer, batch_size=1000)
    assert len(loss_history) == 1


def test_train_accepts_explicit_class_weight():
    """class_weight defaults to None (unweighted, prior behavior); passing
    a weight tensor explicitly must still run and produce finite losses."""
    network = _LSTMPrognosisNet(hidden_size=4)
    optimizer = _optimizer_factory(network.parameters())
    examples = _examples(n=101)
    weight = class_weights(examples)
    loss_history = train(
        network, examples, epochs=2, optimizer=optimizer, batch_size=8, class_weight=weight
    )
    assert len(loss_history) == 2
    assert all(torch.isfinite(torch.tensor(loss)) for loss in loss_history)


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


def test_evaluate_confusion_matrix_sums_to_n_examples():
    network = _LSTMPrognosisNet(hidden_size=4)
    examples = _examples()
    metrics = evaluate(network, examples)
    assert sum(metrics.confusion_matrix.values()) == metrics.n_examples == len(examples)


def test_evaluate_rmse_at_least_mae():
    """Mathematical invariant (RMS >= mean-abs for any real error
    distribution) -- true regardless of the untrained network's actual
    predictions, so it's a safe structural check."""
    network = _LSTMPrognosisNet(hidden_size=4)
    metrics = evaluate(network, _examples())
    assert metrics.rmse_seconds >= metrics.mae_seconds - 1e-9


def test_evaluate_accuracy_and_f1_in_unit_range():
    network = _LSTMPrognosisNet(hidden_size=4)
    metrics = evaluate(network, _examples())
    assert 0.0 <= metrics.accuracy <= 1.0
    assert 0.0 <= metrics.macro_f1 <= 1.0
    for label in ("healthy", "warning", "critical"):
        assert 0.0 <= metrics.per_class_recall[label] <= 1.0
        assert 0.0 <= metrics.per_class_precision[label] <= 1.0


def test_evaluate_puts_network_in_eval_mode():
    network = _LSTMPrognosisNet(hidden_size=4)
    network.train()
    evaluate(network, _examples())
    assert network.training is False


def test_evaluate_rejects_empty_examples():
    network = _LSTMPrognosisNet(hidden_size=4)
    with pytest.raises(ValueError, match="empty"):
        evaluate(network, [])


def test_evaluate_returns_evaluation_metrics_instance():
    network = _LSTMPrognosisNet(hidden_size=4)
    metrics = evaluate(network, _examples())
    assert isinstance(metrics, EvaluationMetrics)


# ---------------------------------------------------------------------------
# leave_one_bearing_out_splits
# ---------------------------------------------------------------------------


def test_lobo_splits_one_fold_per_bearing():
    splits = leave_one_bearing_out_splits(TRAIN_BEARING_IDS)
    assert len(splits) == 4
    held_outs = {held_out for _, held_out in splits}
    assert held_outs == set(TRAIN_BEARING_IDS)


def test_lobo_splits_train_excludes_own_held_out():
    for train_ids, held_out in leave_one_bearing_out_splits(TRAIN_BEARING_IDS):
        assert held_out not in train_ids
        assert set(train_ids) | {held_out} == set(TRAIN_BEARING_IDS)


def test_lobo_splits_deterministic_order():
    splits_a = leave_one_bearing_out_splits(TRAIN_BEARING_IDS)
    splits_b = leave_one_bearing_out_splits(list(reversed(TRAIN_BEARING_IDS)))
    assert splits_a == splits_b


def test_lobo_splits_rejects_fewer_than_two_bearings():
    with pytest.raises(ValueError, match="requires >= 2"):
        leave_one_bearing_out_splits(["Bearing1_1"])


# ---------------------------------------------------------------------------
# run_leave_one_bearing_out
# ---------------------------------------------------------------------------


def _all_sequences(n: int = 35) -> dict[str, PronostiaRunSequence]:
    return {bearing_id: _sequence(n, bearing_id) for bearing_id in TRAIN_BEARING_IDS}


def test_run_lobo_produces_one_fold_per_bearing():
    results = run_leave_one_bearing_out(
        _all_sequences(),
        _trust(),
        hidden_size=4,
        epochs=1,
        batch_size=2,
        optimizer_factory=_optimizer_factory,
    )
    assert len(results) == 4
    assert {r.held_out_bearing for r in results} == set(TRAIN_BEARING_IDS)


def test_run_lobo_fold_train_bearings_exclude_held_out():
    results = run_leave_one_bearing_out(
        _all_sequences(),
        _trust(),
        hidden_size=4,
        epochs=1,
        batch_size=2,
        optimizer_factory=_optimizer_factory,
    )
    for result in results:
        assert result.held_out_bearing not in result.train_bearings
        assert len(result.train_bearings) == 3


def test_run_lobo_class_weighting_enabled_by_default_still_runs():
    """use_class_weighting defaults to True -- must not raise or change the
    result structure relative to the unweighted path."""
    results = run_leave_one_bearing_out(
        _all_sequences(n=101),
        _trust(),
        hidden_size=4,
        epochs=1,
        batch_size=8,
        optimizer_factory=_optimizer_factory,
    )
    assert len(results) == 4
    for result in results:
        assert result.metrics.n_examples > 0


def test_run_lobo_class_weighting_can_be_disabled():
    results = run_leave_one_bearing_out(
        _all_sequences(n=101),
        _trust(),
        hidden_size=4,
        epochs=1,
        batch_size=8,
        optimizer_factory=_optimizer_factory,
        use_class_weighting=False,
    )
    assert len(results) == 4


def test_run_lobo_input_normalization_enabled_by_default_still_runs():
    """use_input_normalization defaults to True -- must not raise or change
    the result structure relative to the unnormalized path."""
    results = run_leave_one_bearing_out(
        _all_sequences(n=101),
        _trust(),
        hidden_size=4,
        epochs=1,
        batch_size=8,
        optimizer_factory=_optimizer_factory,
    )
    assert len(results) == 4
    for result in results:
        assert result.metrics.n_examples > 0


def test_run_lobo_input_normalization_can_be_disabled():
    results = run_leave_one_bearing_out(
        _all_sequences(n=101),
        _trust(),
        hidden_size=4,
        epochs=1,
        batch_size=8,
        optimizer_factory=_optimizer_factory,
        use_input_normalization=False,
    )
    assert len(results) == 4


def test_run_lobo_each_fold_has_metrics_and_loss_history():
    results = run_leave_one_bearing_out(
        _all_sequences(),
        _trust(),
        hidden_size=4,
        epochs=2,
        batch_size=2,
        optimizer_factory=_optimizer_factory,
    )
    for result in results:
        assert len(result.train_loss_history) == 2
        assert isinstance(result.metrics, EvaluationMetrics)
        assert result.metrics.n_examples > 0


def test_run_lobo_rejects_non_training_bearing_id():
    sequences = _all_sequences()
    sequences["Bearing1_4"] = _sequence(35, bearing_id="Bearing1_4")
    with pytest.raises(ValueError, match="unauthorized"):
        run_leave_one_bearing_out(
            sequences,
            _trust(),
            hidden_size=4,
            epochs=1,
            batch_size=2,
            optimizer_factory=_optimizer_factory,
        )


def test_run_lobo_repeated_invocation_produces_consistent_fold_count():
    """Calling run_leave_one_bearing_out twice, independently, must both
    times produce exactly one fold per bearing -- i.e. the function is
    stable/idempotent in its fold structure across repeated calls. This
    does NOT verify per-fold weight independence (that would require
    exposing each fold's trained network, which FoldResult deliberately
    does not do)."""
    results_1 = run_leave_one_bearing_out(
        _all_sequences(),
        _trust(),
        hidden_size=4,
        epochs=1,
        batch_size=2,
        optimizer_factory=_optimizer_factory,
    )
    results_2 = run_leave_one_bearing_out(
        _all_sequences(),
        _trust(),
        hidden_size=4,
        epochs=1,
        batch_size=2,
        optimizer_factory=_optimizer_factory,
    )
    assert len(results_1) == len(results_2) == 4
