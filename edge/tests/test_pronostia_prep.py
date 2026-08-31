"""Tests for edge/eval/pronostia_prep.py (P3 PRONOSTIA raw-data
preprocessing, D021/D022/D023).

Uses small SYNTHETIC fixture CSVs matching PRONOSTIA's actual on-disk
format (no header row; hour/minute/second[,sub-second], value columns) --
never the real ~1.1GB downloaded dataset, which is not committed to this
repo and not required for any test here.
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path

import pytest

from edge.eval.pronostia_prep import PronostiaRunSequence, load_bearing_run


def _write_csv(path: Path, rows: list[tuple]) -> None:
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)


def _temp_rows(hour: int, minute: int, second: int, values: list[float]) -> list[tuple]:
    """One real temp_*.csv file's rows for a single (hour,minute,second):
    sub-second index 0..len(values)-1, matching PRONOSTIA's own format."""
    return [(hour, minute, second, i, v) for i, v in enumerate(values)]


def _acc_rows(
    hour: int, minute: int, second: int, samples: list[tuple[float, float]]
) -> list[tuple]:
    """One real acc_*.csv burst's rows: (hour,minute,second,sub-second-counter,horiz,vert)."""
    return [(hour, minute, second, i * 39, h, v) for i, (h, v) in enumerate(samples)]


def _bearing_dir(tmp_path: Path, name: str = "Bearing1_1") -> Path:
    d = tmp_path / name
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Temperature: 10Hz -> 1Hz block mean (D022 choice 1)
# ---------------------------------------------------------------------------


def test_temperature_block_mean_averages_real_samples(tmp_path: Path):
    """Non-trivial averaging: values 0..9 at one second must average to 4.5,
    proving this is a real mean, not e.g. a first/last-sample pick."""
    d = _bearing_dir(tmp_path)
    _write_csv(d / "temp_00001.csv", _temp_rows(9, 0, 0, [float(i) for i in range(10)]))
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(0.0, 0.0)]))

    seq = load_bearing_run(d, split="training")

    assert seq.temperature == (4.5,)


def test_temperature_multi_second_sequence_length_and_values(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    rows = []
    for second in range(10):
        rows += _temp_rows(9, 0, second, [100.0 + second] * 3)
    _write_csv(d / "temp_00001.csv", rows)
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(1.0, 0.0)]))

    seq = load_bearing_run(d, split="training")

    assert len(seq.temperature) == 10
    assert seq.temperature == tuple(100.0 + s for s in range(10))


# ---------------------------------------------------------------------------
# Vibration: RMS of per-sample Euclidean magnitude (D022 choice 2)
# ---------------------------------------------------------------------------


def test_vibration_rms_of_euclidean_magnitude(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    for second in range(10):
        _write_csv(d / f"temp_{second:05d}.csv", _temp_rows(9, 0, second, [0.0] * 3))
    samples = [(1.0, 0.0), (0.0, 1.0), (3.0, 4.0), (0.0, 0.0)]
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 3, samples))

    seq = load_bearing_run(d, split="training")

    expected_rms = (sum(h**2 + v**2 for h, v in samples) / len(samples)) ** 0.5
    assert seq.vibration[3] == pytest.approx(expected_rms)


# ---------------------------------------------------------------------------
# No interpolation; vibration_observed correctness (D022 choice 3)
# ---------------------------------------------------------------------------


def test_no_interpolation_and_vibration_observed_flag(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    for second in range(10):
        _write_csv(d / f"temp_{second:05d}.csv", _temp_rows(9, 0, second, [20.0] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 2, [(3.0, 4.0)]))  # RMS = 5.0
    _write_csv(d / "acc_00002.csv", _acc_rows(9, 0, 7, [(6.0, 8.0)]))  # RMS = 10.0

    seq = load_bearing_run(d, split="training")

    assert seq.vibration_observed == (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    assert seq.vibration[2] == pytest.approx(5.0)
    assert seq.vibration[7] == pytest.approx(10.0)
    # Every unobserved tick is exactly 0.0 -- never an interpolated value
    # (e.g. not some average of the neighboring 5.0/10.0 observations).
    for i in (0, 1, 3, 4, 5, 6, 8, 9):
        assert seq.vibration[i] == 0.0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_output(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    for second in range(5):
        _write_csv(d / f"temp_{second:05d}.csv", _temp_rows(9, 0, second, [30.0 + second] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 1, [(1.0, 1.0)]))

    first = load_bearing_run(d, split="training")
    second = load_bearing_run(d, split="training")

    assert first == second


# ---------------------------------------------------------------------------
# Bearing identity / split passthrough (train/test separation is the
# caller's responsibility -- this proves the mechanism it depends on:
# distinct, correctly-parsed bearing_id/operating_condition, exact split
# passthrough).
# ---------------------------------------------------------------------------


def test_split_is_stored_exactly_as_supplied_never_inferred(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    _write_csv(d / "temp_00001.csv", _temp_rows(9, 0, 0, [1.0] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(0.0, 0.0)]))

    seq = load_bearing_run(d, split="validation_full")

    assert seq.split == "validation_full"


@pytest.mark.parametrize(
    ("dir_name", "expected_id", "expected_condition"),
    [
        ("Bearing1_1", "Bearing1_1", 1),
        ("Bearing2_1", "Bearing2_1", 2),
        ("Bearing1_2", "Bearing1_2", 1),
        ("Bearing3_3", "Bearing3_3", 3),
    ],
)
def test_bearing_id_and_operating_condition_parsed_distinctly(
    tmp_path: Path, dir_name: str, expected_id: str, expected_condition: int
):
    d = _bearing_dir(tmp_path, dir_name)
    _write_csv(d / "temp_00001.csv", _temp_rows(9, 0, 0, [1.0] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(0.0, 0.0)]))

    seq = load_bearing_run(d, split="training")

    assert seq.bearing_id == expected_id
    assert seq.operating_condition == expected_condition


def test_malformed_bearing_directory_name_raises(tmp_path: Path):
    d = tmp_path / "NotABearing"
    d.mkdir()
    _write_csv(d / "temp_00001.csv", _temp_rows(9, 0, 0, [1.0] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(0.0, 0.0)]))

    with pytest.raises(ValueError):
        load_bearing_run(d, split="training")


# ---------------------------------------------------------------------------
# Original timestamps retained
# ---------------------------------------------------------------------------


def test_original_timestamps_retained(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    _write_csv(d / "temp_00001.csv", _temp_rows(14, 22, 5, [50.0] * 3))
    _write_csv(d / "temp_00002.csv", _temp_rows(14, 22, 6, [51.0] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(14, 22, 5, [(0.0, 0.0)]))

    seq = load_bearing_run(d, split="training")

    assert seq.timestamps == ((14, 22, 5), (14, 22, 6))


# ---------------------------------------------------------------------------
# Day-rollover unwrapping (chronological order must survive midnight)
# ---------------------------------------------------------------------------


def test_midnight_rollover_preserves_chronological_order(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    _write_csv(d / "temp_00001.csv", _temp_rows(23, 59, 58, [1.0] * 3))
    _write_csv(d / "temp_00002.csv", _temp_rows(23, 59, 59, [2.0] * 3))
    _write_csv(d / "temp_00003.csv", _temp_rows(0, 0, 0, [3.0] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(23, 59, 58, [(0.0, 0.0)]))

    seq = load_bearing_run(d, split="training")

    assert seq.timestamps == ((23, 59, 58), (23, 59, 59), (0, 0, 0))
    assert seq.temperature == (1.0, 2.0, 3.0)


def test_non_midnight_backward_jump_raises_not_silently_misattributed(tmp_path: Path):
    """Reproduces the real anomaly found in the actual downloaded
    Bearing1_1 data: a corrupted timestamp that jumps backward but is NOT
    a midnight pattern (e.g. 15:32 -> 09:38, not 23:xx -> 00:xx). Must
    raise, not be silently treated as day-rollover (which would corrupt
    every subsequent elapsed-time value) or silently ignored."""
    d = _bearing_dir(tmp_path)
    _write_csv(d / "temp_00001.csv", _temp_rows(15, 32, 49, [1.0] * 3))
    _write_csv(d / "temp_00002.csv", _temp_rows(9, 38, 46, [2.0] * 3))  # corrupted, not midnight
    _write_csv(d / "acc_00001.csv", _acc_rows(15, 32, 49, [(0.0, 0.0)]))

    with pytest.raises(ValueError, match="NOT consistent with a genuine midnight crossing"):
        load_bearing_run(d, split="training")


# ---------------------------------------------------------------------------
# Delimiter auto-detection (real PRONOSTIA files are inconsistently
# delimited -- some bearings' temp files use ';' instead of ',')
# ---------------------------------------------------------------------------


def test_semicolon_delimited_file_parsed_correctly(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    (d / "temp_00001.csv").write_text(
        "9;0;0;0;70.0\n9;0;0;1;70.0\n9;0;0;2;70.0\n", encoding="utf-8"
    )
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(1.0, 0.0)]))

    seq = load_bearing_run(d, split="training")

    assert seq.temperature == (70.0,)


# ---------------------------------------------------------------------------
# D023 treatment 1: bearings with zero temperature files are excluded
# ---------------------------------------------------------------------------


def test_zero_temperature_bearing_raises_with_d023_attribution(tmp_path: Path):
    """One of D023's five named zero-temperature bearings: still raises
    (no alternative clock is invented), but the message now clearly
    attributes this to the authorized D023 exclusion."""
    d = _bearing_dir(tmp_path, "Bearing2_2")
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(0.0, 0.0)]))

    with pytest.raises(ValueError, match="D023"):
        load_bearing_run(d, split="training")


def test_non_excluded_zero_temperature_bearing_raises_without_d023_note(tmp_path: Path):
    """A bearing NOT in D023's named list that happens to have zero temp
    files still raises (unchanged strict behavior), but without the D023
    attribution note -- proving the note is tied to the actual named set,
    not a blanket claim."""
    d = _bearing_dir(tmp_path, "Bearing2_1")
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(0.0, 0.0)]))

    with pytest.raises(ValueError) as excinfo:
        load_bearing_run(d, split="training")
    assert "D023" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# D023 treatment 2: leading-edge vibration bursts before temperature
# coverage begins are discarded (general rule); genuine internal gaps
# after coverage begins still raise
# ---------------------------------------------------------------------------


def test_leading_edge_bursts_discarded_not_raising(tmp_path: Path):
    d = _bearing_dir(tmp_path, "Bearing2_1")
    # Temperature coverage starts at second=5, not second=0.
    for second in range(5, 10):
        _write_csv(d / f"temp_{second:05d}.csv", _temp_rows(9, 0, second, [50.0] * 3))
    # Leading-edge bursts BEFORE temperature coverage begins -- discarded.
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(1.0, 0.0)]))
    _write_csv(d / "acc_00002.csv", _acc_rows(9, 0, 2, [(1.0, 0.0)]))
    # A real, in-coverage burst.
    _write_csv(d / "acc_00003.csv", _acc_rows(9, 0, 7, [(3.0, 4.0)]))  # RMS = 5.0

    seq = load_bearing_run(d, split="training")

    assert len(seq.temperature) == 5
    assert seq.timestamps[0] == (9, 0, 5)
    assert sum(seq.vibration_observed) == 1.0
    idx = seq.timestamps.index((9, 0, 7))
    assert seq.vibration[idx] == pytest.approx(5.0)


def test_internal_gap_after_coverage_begins_still_raises(tmp_path: Path):
    """A burst at/after temperature coverage begins but still unmatched is
    a genuine internal gap -- NOT covered by D023 treatment 2's
    leading-edge-only scope, and must still raise."""
    d = _bearing_dir(tmp_path, "Bearing2_1")
    for second in (0, 1, 2):
        _write_csv(d / f"temp_{second:05d}.csv", _temp_rows(9, 0, second, [50.0] * 3))
    # Burst at second=5: at/after coverage begins (min covered=0), but 5
    # itself isn't covered -- an internal/trailing gap, not leading-edge.
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 5, [(1.0, 1.0)]))

    with pytest.raises(ValueError, match="genuine internal gap"):
        load_bearing_run(d, split="training")


# ---------------------------------------------------------------------------
# D023 treatment 3: Bearing1_1's two named corrupted files are discarded,
# for Bearing1_1 only -- not a general corrupted-record mechanism
# ---------------------------------------------------------------------------


def test_bearing1_1_corrupted_files_discarded(tmp_path: Path):
    d = _bearing_dir(tmp_path, "Bearing1_1")
    for second in range(10):
        _write_csv(d / f"temp_{second:05d}.csv", _temp_rows(9, 0, second, [60.0] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 1, [(1.0, 0.0)]))
    # The two named corrupted files -- a garbage, non-monotonic timestamp
    # that would otherwise trigger the non-monotonic-jump error.
    _write_csv(d / "acc_02121.csv", _acc_rows(1, 1, 1, [(9.0, 9.0)]))
    _write_csv(d / "acc_02122.csv", _acc_rows(1, 1, 1, [(9.0, 9.0)]))
    _write_csv(d / "acc_02123.csv", _acc_rows(9, 0, 5, [(3.0, 4.0)]))  # RMS = 5.0

    seq = load_bearing_run(d, split="training")

    assert sum(seq.vibration_observed) == 2.0  # only the two clean bursts kept
    idx = seq.timestamps.index((9, 0, 5))
    assert seq.vibration[idx] == pytest.approx(5.0)


def test_treatment_3_filename_exclusion_is_bearing1_1_only(tmp_path: Path):
    """A file coincidentally named acc_02121.csv in a DIFFERENT bearing
    must still be processed normally -- proving treatment 3 checks bearing
    identity, not just the filename."""
    d = _bearing_dir(tmp_path, "Bearing2_1")
    for second in range(3):
        _write_csv(d / f"temp_{second:05d}.csv", _temp_rows(9, 0, second, [10.0] * 3))
    _write_csv(d / "acc_02121.csv", _acc_rows(9, 0, 1, [(3.0, 4.0)]))  # RMS = 5.0

    seq = load_bearing_run(d, split="training")

    assert sum(seq.vibration_observed) == 1.0
    idx = seq.timestamps.index((9, 0, 1))
    assert seq.vibration[idx] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# No fabricated values for the four unapproved channels
# ---------------------------------------------------------------------------


def test_no_fields_exist_for_the_four_unapproved_channels():
    field_names = {f.name for f in dataclasses.fields(PronostiaRunSequence)}
    assert field_names.isdisjoint({"pressure", "humidity", "gas", "current"})


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_vibration_burst_outside_temperature_coverage_raises(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    _write_csv(d / "temp_00001.csv", _temp_rows(9, 0, 0, [1.0] * 3))
    # Burst at second=5, but temperature only covers second=0.
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 5, [(1.0, 1.0)]))

    with pytest.raises(ValueError):
        load_bearing_run(d, split="training")


def test_two_bursts_same_second_raises(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    _write_csv(d / "temp_00001.csv", _temp_rows(9, 0, 0, [1.0] * 3))
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(1.0, 0.0)]))
    _write_csv(d / "acc_00002.csv", _acc_rows(9, 0, 0, [(2.0, 0.0)]))

    with pytest.raises(ValueError):
        load_bearing_run(d, split="training")


def test_missing_temp_files_raises(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    _write_csv(d / "acc_00001.csv", _acc_rows(9, 0, 0, [(0.0, 0.0)]))

    with pytest.raises(ValueError):
        load_bearing_run(d, split="training")


def test_missing_acc_files_raises(tmp_path: Path):
    d = _bearing_dir(tmp_path)
    _write_csv(d / "temp_00001.csv", _temp_rows(9, 0, 0, [1.0] * 3))

    with pytest.raises(ValueError):
        load_bearing_run(d, split="training")
