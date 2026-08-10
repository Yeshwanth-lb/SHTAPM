"""P2 tests — Isolation Forest evaluation harness (plumbing + reproducibility).

These assert ONLY that the diagnostic harness runs deterministically and returns
well-formed structures. They deliberately assert NOTHING about detection
accuracy, false-positive rates, or any P2 acceptance criterion — those are
dataset-gated (U07) and must not be encoded as passing requirements here.

Skipped when scikit-learn is unavailable (same pattern as the IF unit tests).
"""

import pytest

pytest.importorskip("sklearn")

from edge.eval.if_eval import (  # noqa: E402
    BaselineResult,
    CaseResult,
    EvalReport,
    format_report,
    run_eval,
)

_INJECTION_NAMES = {
    "drift",
    "spike",
    "stuck_at",
    "bias_fdi",
    "ramp_fdi",
    "replay",
    "constant_spoof",
}


def test_run_eval_returns_wellformed_report():
    r = run_eval()
    assert isinstance(r, EvalReport)
    assert isinstance(r.baseline, BaselineResult)
    assert {c.injection for c in r.cases} == _INJECTION_NAMES  # all 7 §12.4 hardware-free
    assert all(isinstance(c, CaseResult) for c in r.cases)


def test_all_severities_in_unit_interval():
    r = run_eval()
    b = r.baseline
    for s in (b.severity_min, b.severity_median, b.severity_max):
        assert 0.0 <= s <= 1.0
    for c in r.cases:
        assert 0.0 <= c.peak_severity_overlap <= 1.0
        if c.peak_severity_inside is not None:
            assert 0.0 <= c.peak_severity_inside <= 1.0


def test_deterministic_across_runs():
    # Fixed simulator seed + IF random_state + index-derived timestamps -> identical.
    r1 = run_eval()
    r2 = run_eval()
    assert r1.baseline == r2.baseline
    assert r1.cases == r2.cases


def test_false_positive_fields_consistent():
    b = run_eval().baseline
    assert 0 <= b.false_positives <= b.n_windows
    assert b.fp_rate == pytest.approx(b.false_positives / b.n_windows)


def test_report_string_carries_non_acceptance_disclaimer():
    text = format_report(run_eval())
    assert "NOT acceptance" in text
    assert "dataset-gated" in text
    # every injection name appears in the rendered table
    for name in _INJECTION_NAMES:
        assert name in text
