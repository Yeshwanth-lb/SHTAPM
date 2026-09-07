"""Tests for edge/eval/u05_capture_loader.py -- hardware-free, fixture-only.
No real capture file, real sensor, or real hardware claim is involved here.
"""

from __future__ import annotations

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Preprocessor
from edge.eval.u05_capture_loader import (
    CaptureLoadResult,
    load_telemetry_capture,
    ordered_messages,
    raw_channel_values_for_window,
    windows_from_capture,
)

_SENSORS = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.0,
}


def _line(seq: int, ts: str = "2026-09-07T00:00:00.000Z") -> str:
    msg = build_telemetry("pump-01", ts, _SENSORS, sample_seq=seq)
    return msg.model_dump_json()


def test_loads_valid_lines():
    lines = [_line(0), _line(1), _line(2)]
    result = load_telemetry_capture(lines)
    assert len(result.messages) == 3
    assert result.rejected_line_count == 0
    assert result.execution_mode == "offline_analysis"
    assert result.model_status == "diagnostic_unvalidated"


def test_blank_lines_skipped_not_counted_as_rejected():
    lines = [_line(0), "", "   ", _line(1)]
    result = load_telemetry_capture(lines)
    assert len(result.messages) == 2
    assert result.rejected_line_count == 0


def test_malformed_lines_rejected_and_counted_never_raised():
    lines = [_line(0), "not-json{", '{"device_id":"pump-01"}', _line(1)]
    result = load_telemetry_capture(lines)
    assert len(result.messages) == 2
    assert result.rejected_line_count == 2


def test_tolerates_a_leading_topic_prefix_like_mosquitto_sub_dash_v():
    prefixed = f"shtapm/pump-01/telemetry {_line(0)}"
    result = load_telemetry_capture([prefixed])
    assert len(result.messages) == 1
    assert result.rejected_line_count == 0


def test_ordered_messages_sorts_by_sample_seq_even_if_captured_out_of_order():
    lines = [_line(2), _line(0), _line(1)]
    result = load_telemetry_capture(lines)
    ordered = ordered_messages(result)
    assert [m.sample_seq for m in ordered] == [0, 1, 2]


def test_windows_from_capture_reuses_the_existing_unmodified_preprocessor():
    # window_size=3, step=1 -> exactly 3 windows from 5 frames (5-3+1=3)
    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=3, step=1)
    lines = [_line(i) for i in range(5)]
    result = load_telemetry_capture(lines)
    windows = windows_from_capture(result, preprocessor)
    assert len(windows) == 3
    assert windows[0].start_index == 0 and windows[0].end_index == 3
    assert windows[-1].start_index == 2 and windows[-1].end_index == 5


def test_windows_from_capture_empty_when_shorter_than_one_window():
    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=30, step=1)
    result = load_telemetry_capture([_line(0), _line(1)])
    assert windows_from_capture(result, preprocessor) == []


def test_raw_channel_values_for_window_uses_the_last_message_in_range():
    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=3, step=1)
    values_per_frame = [
        {**_SENSORS, "vibration": 0.1},
        {**_SENSORS, "vibration": 0.2},
        {**_SENSORS, "vibration": 0.3},
    ]
    lines = [
        build_telemetry("pump-01", "2026-09-07T00:00:00.000Z", v, sample_seq=i).model_dump_json()
        for i, v in enumerate(values_per_frame)
    ]
    result = load_telemetry_capture(lines)
    messages = ordered_messages(result)
    windows = windows_from_capture(result, preprocessor)
    assert len(windows) == 1
    raw = raw_channel_values_for_window(windows[0], messages)
    assert raw["vibration"] == 0.3  # the last (most recent) frame in the window
    assert set(raw) == set(CHANNELS)


def test_capture_load_result_is_a_frozen_dataclass_shape():
    result = load_telemetry_capture([_line(0)])
    assert isinstance(result, CaptureLoadResult)
    assert result.messages[0].sample_seq == 0
