"""Bench twin training data handling (D039): capture formats, contiguity across
files and time gaps, and masking of channels the twin may not read."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("torch")

from edge.eval.bench_twin_training import (  # noqa: E402
    WINDOW_SIZE,
    build_windows,
    fit_scaler,
    load_capture,
    load_captures,
)


def _telemetry_row(second: int, current: float) -> dict:
    return {
        "device_id": "pump-01",
        "ts": f"2026-10-27T06:{second // 60:02d}:{second % 60:02d}.000Z",
        "sensors": {
            "temperature": 26.0,
            "vibration": 0.5,
            "pressure": 916.0,
            "humidity": 45.0,
            "gas": 150.0,
            "current": current,
        },
        "sample_seq": second,
    }


def _write(path, rows) -> str:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return str(path)


def test_reads_edge_telemetry_rows(tmp_path):
    path = _write(tmp_path / "t.jsonl", [_telemetry_row(s, 0.7) for s in range(3)])
    samples = load_capture(path)
    assert [s.values["current"] for s in samples] == [0.7, 0.7, 0.7]
    assert set(samples[0].values) == {"temperature", "vibration", "pressure", "humidity", "current"}


def test_reads_load_capture_rows_and_drops_unhealthy(tmp_path):
    good = {
        "temperature_c": 27.2,
        "vibration_g_driver": 0.1,
        "pressure_hpa": 917.9,
        "humidity_pct": 58.2,
        "current_a": 0.0,
    }
    path = _write(tmp_path / "l.jsonl", [good, {**good, "humidity_pct": None}, good])
    samples = load_capture(path)
    assert len(samples) == 2
    assert samples[1].index - samples[0].index == 2  # the dropped row still breaks contiguity


def test_a_telemetry_time_gap_is_never_one_window(tmp_path):
    rows = [_telemetry_row(s, 0.7) for s in range(WINDOW_SIZE)]
    rows += [_telemetry_row(s + 600, 0.7) for s in range(WINDOW_SIZE)]  # 10 min later
    samples = load_capture(_write(tmp_path / "gap.jsonl", rows))
    windows = build_windows(samples, fit_scaler(samples))
    assert len(windows) == 2  # one per contiguous half, none across the gap


def test_windows_never_span_two_captures(tmp_path):
    a = _write(tmp_path / "a.jsonl", [_telemetry_row(s, 0.7) for s in range(WINDOW_SIZE)])
    b = _write(tmp_path / "b.jsonl", [_telemetry_row(s, 0.0) for s in range(WINDOW_SIZE)])
    samples = load_captures([a, b])
    windows = build_windows(samples, fit_scaler(samples))
    assert len(windows) == 2


def test_channels_outside_inputs_are_masked_and_unfitted(tmp_path):
    rows = [_telemetry_row(s, 0.7 if s % 2 else 0.0) for s in range(WINDOW_SIZE)]
    samples = load_capture(_write(tmp_path / "m.jsonl", rows))
    scaler = fit_scaler(samples, ("current", "vibration"))
    assert scaler.fitted_channels == frozenset({"current", "vibration"})
    (window,) = build_windows(samples, scaler)
    for ch in ("temperature", "pressure", "humidity", "gas"):
        assert window.features[ch] == (0.0,) * WINDOW_SIZE
    assert window.features["current"] != (0.0,) * WINDOW_SIZE


def test_a_dropout_on_a_channel_the_twin_does_not_read_keeps_the_row(tmp_path):
    good = {
        "temperature_c": 27.2,
        "vibration_g_driver": 0.1,
        "pressure_hpa": 917.9,
        "humidity_pct": 58.2,
        "current_a": 0.0,
    }
    path = _write(tmp_path / "d.jsonl", [good, {**good, "humidity_pct": None}, good])
    assert len(load_capture(path, required=("current", "vibration"))) == 3
    assert len(load_capture(path)) == 2
