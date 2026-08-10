"""P2 tests — normalization-variant experiment (plumbing + reproducibility).

Assert ONLY that the diagnostic experiment runs deterministically and returns
well-formed structures for all three variants. They assert NOTHING about which
variant is better, any false-positive target, or any P2 acceptance criterion —
those are dataset-gated (U07).

Skipped when scikit-learn is unavailable (same pattern as the IF unit tests).
"""

import pytest

pytest.importorskip("sklearn")

from edge.eval.preproc_experiment import (  # noqa: E402
    VariantResult,
    format_report,
    run_experiment,
)

_VARIANTS = {"A_per_window_minmax", "B_global_minmax", "C_zscore"}
_INJECTIONS = {"drift", "spike", "stuck_at", "bias_fdi", "ramp_fdi", "replay", "constant_spoof"}


def test_experiment_wellformed():
    results = run_experiment()
    assert {r.name for r in results} == _VARIANTS
    for r in results:
        assert isinstance(r, VariantResult)
        assert {c.injection for c in r.cases} == _INJECTIONS
        assert 0.0 <= r.clean_fp_rate <= 1.0
        for s in (r.clean_sev_min, r.clean_sev_median, r.clean_sev_max):
            assert 0.0 <= s <= 1.0
        for c in r.cases:
            assert 0.0 <= c.overlap_peak <= 1.0
            if c.inside_peak is not None:
                assert 0.0 <= c.inside_peak <= 1.0


def test_experiment_deterministic():
    r1 = run_experiment()
    r2 = run_experiment()
    assert r1 == r2  # fixed seeds + IF random_state -> identical


def test_report_disclaimer_present():
    text = format_report(run_experiment())
    assert "DIAGNOSTIC, NOT acceptance" in text
    assert "dataset-gated" in text or "SWaT/WADI/TEP" in text
