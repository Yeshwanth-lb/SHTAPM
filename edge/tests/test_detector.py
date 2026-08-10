"""P2 tests — anomaly-detector seam + NullDetector + AnomalyResult.

Validate the interface/plumbing only. The NullDetector is a placeholder that
never flags; these tests assert exactly that, and make NO claim about real
anomaly detection.
"""

import pytest
from app.schemas.contracts import CHANNELS

from edge.anomaly.detector import (
    AnomalyDetector,
    AnomalyResult,
    NullDetector,
    detect,
)
from edge.anomaly.preprocess import Window


def _window(value: float, size: int = 4) -> Window:
    return Window(
        start_index=0,
        end_index=size,
        features={ch: tuple([value] * size) for ch in CHANNELS},
    )


# --- AnomalyResult -----------------------------------------------------------


def test_anomaly_result_holds_flag_and_severity():
    r = AnomalyResult(flag=True, severity=0.5)
    assert r.flag is True and r.severity == 0.5


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0])
def test_anomaly_result_rejects_out_of_range_severity(bad):
    with pytest.raises(ValueError):
        AnomalyResult(flag=False, severity=bad)


# --- NullDetector ------------------------------------------------------------


def test_null_detector_satisfies_protocol():
    assert isinstance(NullDetector(), AnomalyDetector)


def test_null_detector_never_flags_any_window():
    det = NullDetector()
    for v in (0.0, 1.0, 1e9, -1e9):  # even wildly "anomalous" values
        w = _window(v)
        assert det.score(w) == 0.0
        assert det.flag(w) is False


def test_null_detector_fit_is_noop_but_records():
    det = NullDetector()
    assert det.fitted is False
    det.fit([_window(0.0), _window(1.0)])
    assert det.fitted is True and det.fit_count == 2


def test_detect_packages_result():
    det = NullDetector()
    r = detect(det, _window(5.0))
    assert isinstance(r, AnomalyResult)
    assert r.flag is False and r.severity == 0.0
