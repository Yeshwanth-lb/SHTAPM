"""Tests for edge/models/twin_bundle.py (P3 · D029).

A bundle exists so a checkpoint can never be loaded against a scale or residual
distribution it was not trained with. These tests hold that guarantee.
"""

from __future__ import annotations

import json

import pytest

from edge.models.lstm_twin import LSTMTwinReconstructor, _LSTMTwinNet
from edge.models.scaling import ChannelScaler
from edge.models.twin_bundle import BUNDLE_FORMAT_VERSION, load_bundle, save_bundle

HIDDEN_SIZE_FIXTURE = 4


def _save(tmp_path, **overrides):
    scaler = ChannelScaler()
    scaler.fit({"current": [0.0, 0.5, 1.0], "vibration": [0.1, 0.2, 0.3]})
    kwargs = {
        "channel": "current",
        "reconstructor": LSTMTwinReconstructor(_LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)),
        "scaler": scaler,
        "residual_mean": 0.25,
        "residual_std": 0.75,
        "hidden_size": HIDDEN_SIZE_FIXTURE,
        "skill": 0.458,
        "trained_on": "motor_load_full.jsonl",
    }
    kwargs.update(overrides)
    path = tmp_path / "twin_current"
    save_bundle(path, **kwargs)
    return path, scaler


def test_round_trip_preserves_scale_exactly(tmp_path):
    """The scale must survive the round trip: a reconstruction is only
    invertible to engineering units on the scale it was trained under."""
    path, original = _save(tmp_path)
    loaded = load_bundle(path)

    for channel in ("current", "vibration"):
        for raw in (-1.0, 0.0, 0.42, 3.0):
            assert loaded.scaler.normalize(channel, raw) == pytest.approx(
                original.normalize(channel, raw)
            )


def test_round_trip_preserves_residual_statistics(tmp_path):
    path, _ = _save(tmp_path)
    loaded = load_bundle(path)
    assert loaded.residual_mean == pytest.approx(0.25)
    assert loaded.residual_std == pytest.approx(0.75)


def test_divergence_fit_reproduces_the_recorded_distribution(tmp_path):
    """DivergenceScorer fitted from the bundle must score residuals exactly as
    the training-time scorer did, or a deployed threshold means nothing."""
    from edge.pipeline.divergence import DivergenceScorer

    path, _ = _save(tmp_path)
    loaded = load_bundle(path)

    scorer = DivergenceScorer()
    scorer.fit(loaded.divergence_fit())

    # A residual exactly one std from the recorded mean must score 1.0 sigma.
    assert scorer.score("current", 0.25 + 0.75) == pytest.approx(1.0)
    assert scorer.score("current", 0.25) == pytest.approx(0.0)


def test_reconstruction_is_reproducible_after_reload(tmp_path):
    """Same window, same output -- the weights actually round-trip."""
    from app.schemas.contracts import CHANNELS

    from edge.anomaly.preprocess import Window

    path, _ = _save(tmp_path)
    original = load_bundle(path)
    reloaded = load_bundle(path)

    window = Window(start_index=0, end_index=30, features={ch: (0.3,) * 30 for ch in CHANNELS})
    assert original.reconstructor.reconstruct(window, "current") == pytest.approx(
        reloaded.reconstructor.reconstruct(window, "current")
    )


def test_provenance_is_recorded(tmp_path):
    """A deployed twin must be traceable to the evidence behind it."""
    path, _ = _save(tmp_path)
    loaded = load_bundle(path)
    assert loaded.trained_on == "motor_load_full.jsonl"
    assert loaded.skill == pytest.approx(0.458)


def test_unknown_format_version_refuses_to_load(tmp_path):
    path, _ = _save(tmp_path)
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    metadata["format_version"] = BUNDLE_FORMAT_VERSION + 1
    path.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="format_version"):
        load_bundle(path)


def test_unknown_channel_refuses_to_load(tmp_path):
    path, _ = _save(tmp_path)
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    metadata["channel"] = "not_a_channel"
    path.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown channel"):
        load_bundle(path)


def test_missing_files_raise(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_bundle(tmp_path / "does_not_exist")
