"""P2 tests — SWaT.A1 evaluation harness (plumbing + label-normalization only).

These assert ONLY that the harness's pure-logic pieces (label normalization,
timestamp conversion, D012 mapping) behave correctly, and that a real run
produces a well-formed report WHEN the (access-restricted, gitignored) SWaT
dataset files are present locally. They deliberately assert NOTHING about
detection accuracy, false-positive rates, or any P2 acceptance criterion.

Skipped entirely when scikit-learn or the dataset files are unavailable (the
dataset can never be checked into CI — iTrust Terms of Usage forbid
redistribution; see DECISIONS.md D011/D012).
"""

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("openpyxl")

from types import SimpleNamespace  # noqa: E402

from edge.eval.swat_eval import (  # noqa: E402
    ATTACK_FILENAME,
    DEFAULT_DATA_DIR,
    NORMAL_FILENAME,
    STEP,
    TAG_MAP,
    WINDOW_SIZE,
    ConfusionMatrix,
    LatencyReport,
    attack_onsets,
    compute_latency,
    normalize_label,
    swat_timestamp_to_iso,
)


def _fake_outcome(flagged: bool):
    """Minimal stand-in for a WindowOutcome: compute_latency only reads
    ``.anomaly.flag``."""
    return SimpleNamespace(anomaly=SimpleNamespace(flag=flagged))


_DATASET_PRESENT = (DEFAULT_DATA_DIR / NORMAL_FILENAME).exists() and (
    DEFAULT_DATA_DIR / ATTACK_FILENAME
).exists()


def test_d012_mapping_is_exactly_six_frozen_channels():
    from app.schemas.contracts import CHANNELS

    assert set(TAG_MAP.keys()) == set(CHANNELS)
    assert TAG_MAP["gas"] == "AIT402"  # D012: proxy slot, not a physical claim


def test_normalize_label_handles_the_known_typo():
    assert normalize_label("Normal") == "Normal"
    assert normalize_label("Attack") == "Attack"
    assert normalize_label("A ttack") == "Attack"  # confirmed 37-row data-quality issue
    assert normalize_label("  Attack  ") == "Attack"


def test_normalize_label_rejects_unknown_values():
    with pytest.raises(ValueError):
        normalize_label("Unknown")


def test_swat_timestamp_to_iso_format():
    iso = swat_timestamp_to_iso(" 22/12/2015 4:30:00 PM")
    assert iso == "2015-12-22T16:30:00.000Z"


def test_swat_timestamp_am_pm_boundary():
    assert swat_timestamp_to_iso("28/12/2015 12:00:00 AM") == "2015-12-28T00:00:00.000Z"
    assert swat_timestamp_to_iso("28/12/2015 12:00:00 PM") == "2015-12-28T12:00:00.000Z"


def test_confusion_matrix_rates():
    cm = ConfusionMatrix(tp=8, fp=2, tn=18, fn=2)
    assert cm.n == 30
    assert cm.fp_rate == pytest.approx(2 / 20)
    assert cm.detection_rate == pytest.approx(8 / 10)


def test_confusion_matrix_rates_handle_empty_buckets():
    cm = ConfusionMatrix()
    assert cm.fp_rate == 0.0
    assert cm.detection_rate == 0.0


def test_step_equals_window_size_precondition():
    # compute_latency's row->window floor-division mapping assumes this.
    assert STEP == WINDOW_SIZE


def test_attack_onsets_detects_each_contiguous_run_start():
    labels = ["Normal", "Normal", "Attack", "Attack", "Normal", "Attack", "Normal"]
    # start=0: onsets at index 2 (Normal->Attack) and index 5 (Normal->Attack).
    assert attack_onsets(labels, start=0) == [2, 5]


def test_attack_onsets_counts_start_index_already_attack_as_onset():
    labels = ["Attack", "Attack", "Normal"]
    assert attack_onsets(labels, start=0) == [0]


def test_attack_onsets_respects_start_offset():
    labels = ["Attack", "Normal", "Attack", "Attack"]
    # The leading "Attack" at index 0 is before `start` and must be ignored;
    # index 2 is a genuine Normal->Attack transition within [start, end).
    assert attack_onsets(labels, start=1) == [2]


def test_compute_latency_immediate_detection():
    # onset at row 0 (eval_boundary=0); the covering window (index 0) is
    # itself flagged -> latency == 1.
    labels = ["Attack"] * WINDOW_SIZE
    outcomes = [_fake_outcome(flagged=True)]
    report = compute_latency(outcomes, labels, eval_boundary=0)
    assert report.n_onsets == 1
    assert report.n_flagged == 1
    assert report.latencies_windows == [1]
    assert report.n_never_flagged == 0
    assert report.n_not_evaluable == 0


def test_compute_latency_delayed_detection():
    # Covering window (0) not flagged, next window (1) is -> latency == 2.
    labels = ["Attack"] * (WINDOW_SIZE * 2)
    outcomes = [_fake_outcome(flagged=False), _fake_outcome(flagged=True)]
    report = compute_latency(outcomes, labels, eval_boundary=0)
    assert report.latencies_windows == [2]


def test_compute_latency_never_flagged_is_counted_separately_not_averaged():
    labels = ["Attack"] * (WINDOW_SIZE * 2)
    outcomes = [_fake_outcome(flagged=False), _fake_outcome(flagged=False)]
    report = compute_latency(outcomes, labels, eval_boundary=0)
    assert report.n_onsets == 1
    assert report.n_never_flagged == 1
    assert report.n_flagged == 0
    assert report.latencies_windows == []
    assert (
        report.mean_latency_windows is None
    )  # never silently averaged as 0 or excluded-as-if-perfect


def test_compute_latency_not_evaluable_when_onset_beyond_produced_windows():
    # Onset row falls past the single produced window's coverage.
    labels = ["Normal"] * WINDOW_SIZE + ["Attack"] * WINDOW_SIZE
    outcomes = [_fake_outcome(flagged=True)]  # only one window produced (e.g. a --limit slice)
    report = compute_latency(outcomes, labels, eval_boundary=0)
    assert report.n_onsets == 1
    assert report.n_not_evaluable == 1
    assert report.n_never_flagged == 0
    assert report.n_flagged == 0


def test_compute_latency_multiple_onsets_independent():
    # Two separate attack runs, each in its own window; first misses, second hits.
    labels = ["Attack"] * WINDOW_SIZE + ["Normal"] * WINDOW_SIZE + ["Attack"] * WINDOW_SIZE
    outcomes = [
        _fake_outcome(flagged=False),
        _fake_outcome(flagged=False),
        _fake_outcome(flagged=True),
    ]
    report = compute_latency(outcomes, labels, eval_boundary=0)
    assert report.n_onsets == 2
    assert report.n_never_flagged == 1
    assert report.n_flagged == 1
    assert report.latencies_windows == [1]  # third window flagged immediately for the 2nd onset


def test_latency_report_properties_are_none_when_nothing_flagged():
    r = LatencyReport(n_onsets=1, n_not_evaluable=0, n_never_flagged=1, latencies_windows=[])
    assert r.mean_latency_windows is None
    assert r.median_latency_windows is None
    assert r.max_latency_windows is None
    assert r.n_flagged == 0


@pytest.mark.skipif(
    not _DATASET_PRESENT, reason="SWaT.A1 dataset not present locally (never in CI)"
)
def test_run_eval_returns_wellformed_report_on_small_slice():
    from edge.eval.swat_eval import run_eval

    # Small --limit slice only, for a fast structural check — not a real result.
    report = run_eval(limit=200)
    assert report.n_eval_windows >= 0
    assert 0.0 <= report.confusion.fp_rate <= 1.0
    assert 0.0 <= report.confusion.detection_rate <= 1.0


@pytest.mark.skipif(
    not _DATASET_PRESENT, reason="SWaT.A1 dataset not present locally (never in CI)"
)
def test_format_report_carries_disclaimers():
    from edge.eval.swat_eval import format_report, run_eval

    text = format_report(run_eval(limit=200))
    assert "NOT P2 acceptance" in text
    assert "AIT402" in text
    assert "plumbing/proxy substitution ONLY" in text
