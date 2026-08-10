"""P2 tests — documented preprocessing pipeline (shape/semantics only).

Validate the filter/normalize/window mechanics, NOT detection or tuning. All
filter parameters here are **TEST FIXTURES ONLY — arbitrary, not project specs.**
"""

import pytest
from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import (
    Preprocessor,
    Window,
    low_pass_filter,
    median_filter,
    min_max_normalize,
)

DEVICE = "pump-01"


def _ts(i: int) -> str:
    return f"2026-08-10T00:00:{i:02d}.000Z"


def _stream(values_per_index):
    """Build frames where every channel takes the given value at each index."""
    return [
        build_telemetry(DEVICE, _ts(i), {ch: float(v) for ch in CHANNELS}, i)
        for i, v in enumerate(values_per_index)
    ]


# --- median filter -----------------------------------------------------------


def test_median_removes_single_spike():
    out = median_filter([1, 1, 9, 1, 1], kernel=3)  # kernel: TEST FIXTURE
    assert out == [1, 1, 1, 1, 1]


def test_median_kernel_1_is_identity():
    assert median_filter([3.0, 1.0, 2.0], kernel=1) == [3.0, 1.0, 2.0]


@pytest.mark.parametrize("bad", [0, -1, 2, 4])
def test_median_rejects_non_odd_positive_kernel(bad):
    with pytest.raises(ValueError):
        median_filter([1, 2, 3], kernel=bad)


# --- low-pass filter ---------------------------------------------------------


def test_low_pass_alpha_1_is_identity():
    assert low_pass_filter([1.0, 5.0, 2.0], alpha=1.0) == [1.0, 5.0, 2.0]


def test_low_pass_smooths_toward_input():
    out = low_pass_filter([0.0, 10.0, 10.0], alpha=0.5)  # alpha: TEST FIXTURE
    assert out[0] == 0.0
    assert out[1] == pytest.approx(5.0)  # 0.5*10 + 0.5*0
    assert out[2] == pytest.approx(7.5)  # 0.5*10 + 0.5*5
    assert out[1] < 10.0 and out[2] < 10.0  # lags the step


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_low_pass_rejects_bad_alpha(bad):
    with pytest.raises(ValueError):
        low_pass_filter([1.0, 2.0], alpha=bad)


# --- min-max normalize -------------------------------------------------------


def test_min_max_scales_to_unit_interval():
    out = min_max_normalize([10.0, 20.0, 30.0])
    assert out == [0.0, 0.5, 1.0]


def test_min_max_flat_sequence_maps_to_zeros():
    assert min_max_normalize([7.0, 7.0, 7.0]) == [0.0, 0.0, 0.0]


# --- windowing / full pipeline ----------------------------------------------


def test_default_window_size_is_documented_30():
    assert Preprocessor(median_kernel=1, low_pass_alpha=1.0).window_size == 30


def test_windows_count_and_indices():
    frames = _stream(range(5))
    pp = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=3, step=1)
    windows = pp.process(frames)
    assert len(windows) == 3  # [0,3), [1,4), [2,5)
    assert [(w.start_index, w.end_index) for w in windows] == [(0, 3), (1, 4), (2, 5)]
    assert all(w.size == 3 for w in windows)


def test_stream_shorter_than_window_yields_empty():
    frames = _stream(range(2))
    pp = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=3)
    assert pp.process(frames) == []


def test_pipeline_outputs_normalized_windows_all_channels():
    frames = _stream(range(4))  # values 0,1,2,3 on every channel
    pp = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=4)
    (w,) = pp.process(frames)
    for ch in CHANNELS:
        vals = w.features[ch]
        assert len(vals) == 4
        assert min(vals) == 0.0 and max(vals) == 1.0  # normalized within window
        assert vals == (0.0, pytest.approx(1 / 3), pytest.approx(2 / 3), 1.0)


def test_window_as_matrix_shape_and_order():
    frames = _stream(range(3))
    pp = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=3)
    (w,) = pp.process(frames)
    m = w.as_matrix()
    assert len(m) == 3  # rows = samples
    assert all(len(row) == len(CHANNELS) for row in m)  # cols = channels


@pytest.mark.parametrize("kw", [{"window_size": 0}, {"step": 0}, {"median_kernel": 2}])
def test_preprocessor_rejects_bad_config(kw):
    base = {"median_kernel": 1, "low_pass_alpha": 1.0}
    base.update(kw)
    with pytest.raises(ValueError):
        Preprocessor(**base)


def test_preprocessor_requires_filter_params():
    # median_kernel and low_pass_alpha are required (no invented spec defaults).
    with pytest.raises(TypeError):
        Preprocessor(window_size=30)  # type: ignore[call-arg]


def test_window_is_frozen():
    w = Window(start_index=0, end_index=1, features={ch: (0.0,) for ch in CHANNELS})
    with pytest.raises((AttributeError, TypeError)):
        w.start_index = 5  # type: ignore[misc]
