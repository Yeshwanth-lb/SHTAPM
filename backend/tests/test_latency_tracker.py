"""LatencyTracker tests.

The property that matters most: clock skew must surface as "cannot measure",
never as a plausible-looking number.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.services.latency_tracker import LatencyTracker

BASE = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def test_no_samples_reports_none_not_zero():
    """A missing measurement and a 0 ms measurement mean very different things."""
    snapshot = LatencyTracker().snapshot()
    assert snapshot.samples == 0
    assert snapshot.p50_ms is None
    assert snapshot.p95_ms is None


def test_measures_edge_to_backend_delta():
    tracker = LatencyTracker()
    tracker.record(_iso(BASE), received_at=BASE + timedelta(milliseconds=120))

    snapshot = tracker.snapshot()
    assert snapshot.samples == 1
    assert snapshot.p50_ms == pytest.approx(120.0, abs=1.0)


def test_percentiles_over_many_samples():
    tracker = LatencyTracker()
    for ms in range(1, 101):
        tracker.record(_iso(BASE), received_at=BASE + timedelta(milliseconds=ms))

    snapshot = tracker.snapshot()
    assert snapshot.samples == 100
    assert snapshot.p50_ms == pytest.approx(50.0, abs=1.0)
    assert snapshot.p95_ms == pytest.approx(95.0, abs=1.0)
    assert snapshot.max_ms == pytest.approx(100.0, abs=1.0)


def test_negative_latency_suppresses_the_figure_entirely():
    """A frame cannot arrive before it was sent. That means the edge and backend
    clocks disagree, and every figure from the same clock pair is suspect --
    so no number is reported at all."""
    tracker = LatencyTracker()
    for ms in (10, 20, 30):
        tracker.record(_iso(BASE), received_at=BASE + timedelta(milliseconds=ms))
    tracker.record(_iso(BASE), received_at=BASE - timedelta(milliseconds=500))

    snapshot = tracker.snapshot()
    assert snapshot.clock_skew_suspected is True
    assert snapshot.negative_samples == 1
    assert snapshot.p50_ms is None, "a skewed clock must not yield a plausible number"


def test_negative_samples_are_not_clamped_to_zero():
    """Clamping would turn "the clocks disagree" into a healthy-looking 0 ms."""
    tracker = LatencyTracker()
    tracker.record(_iso(BASE), received_at=BASE - timedelta(seconds=5))

    snapshot = tracker.snapshot()
    assert snapshot.samples == 0
    assert snapshot.negative_samples == 1


def test_window_is_bounded():
    """A long-running backend must not accumulate samples without limit."""
    tracker = LatencyTracker(window=10)
    for ms in range(1, 51):
        tracker.record(_iso(BASE), received_at=BASE + timedelta(milliseconds=ms))

    assert tracker.snapshot().samples == 10


def test_malformed_timestamp_is_ignored_not_raised():
    """This runs on the MQTT ingest path; a bad frame must not break it."""
    tracker = LatencyTracker()
    tracker.record("not-a-timestamp")
    tracker.record("")
    assert tracker.snapshot().samples == 0


def test_naive_timestamp_is_treated_as_utc():
    tracker = LatencyTracker()
    tracker.record("2026-09-18T12:00:00.000", received_at=BASE + timedelta(milliseconds=50))
    assert tracker.snapshot().samples == 1
