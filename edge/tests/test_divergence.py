"""Tests for edge/pipeline/divergence.py (P3 · D018 pt.1).

All numeric residual/threshold values below are TEST FIXTURES for exercising
the z-score arithmetic -- none is presented as, or should be read as, the
project's divergence_threshold specification (U05, still data-gated).
"""

import pytest

from edge.pipeline.divergence import DivergenceScorer


def test_fit_requires_at_least_one_channel():
    scorer = DivergenceScorer()
    with pytest.raises(ValueError):
        scorer.fit({})


def test_fit_rejects_empty_residual_sequence():
    scorer = DivergenceScorer()
    with pytest.raises(ValueError):
        scorer.fit({"temperature": []})


def test_fit_rejects_unknown_channel():
    scorer = DivergenceScorer()
    with pytest.raises(ValueError):
        scorer.fit({"not_a_channel": [1.0, 2.0]})


def test_score_before_fit_raises():
    scorer = DivergenceScorer()
    with pytest.raises(RuntimeError):
        scorer.score("temperature", 1.0)


def test_score_unknown_channel_raises():
    scorer = DivergenceScorer()
    scorer.fit({"temperature": [0.0, 1.0]})
    with pytest.raises(ValueError):
        scorer.score("not_a_channel", 1.0)


def test_fitted_property():
    scorer = DivergenceScorer()
    assert scorer.fitted is False
    scorer.fit({"temperature": [0.0, 1.0]})
    assert scorer.fitted is True


def test_score_zero_at_training_mean():
    scorer = DivergenceScorer()
    scorer.fit({"temperature": [0.0, 2.0, 4.0]})  # mean=2.0
    assert scorer.score("temperature", 2.0) == pytest.approx(0.0)


def test_score_increases_with_distance_from_mean():
    scorer = DivergenceScorer()
    scorer.fit({"temperature": [-1.0, 0.0, 1.0]})  # mean=0.0
    near = scorer.score("temperature", 0.5)
    far = scorer.score("temperature", 5.0)
    assert 0.0 < near < far


def test_partial_channel_fit_only_scores_fitted_channels():
    scorer = DivergenceScorer()
    scorer.fit({"current": [1.0, 2.0, 3.0]})
    assert scorer.score("current", 2.0) == pytest.approx(0.0)
    with pytest.raises(RuntimeError):
        scorer.score("vibration", 1.0)


def test_second_fit_call_adds_without_clearing_existing_channels():
    scorer = DivergenceScorer()
    scorer.fit({"current": [1.0, 2.0, 3.0]})
    scorer.fit({"vibration": [0.0, 0.0, 0.0]})
    # "current" fitted by the first call must still be usable.
    assert scorer.score("current", 2.0) == pytest.approx(0.0)
