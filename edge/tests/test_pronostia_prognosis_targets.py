"""Tests for edge/eval/pronostia_prognosis_targets.py (P3 PRONOSTIA
prognosis target generation, D025/D026).

Uses small SYNTHETIC PronostiaRunSequence fixtures only -- never the real
~1.1GB downloaded dataset, and never Validation_Set/Full_Test_Set or any
test-split bearing. Loader-level testing remains the responsibility of
test_pronostia_prep.py; input-tensor glue testing remains the
responsibility of test_pronostia_prognosis_input.py. This file tests only
the D025/D026 target-generation mapping from an already-built
PronostiaRunSequence to RUL/HealthState targets.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import HealthState

from edge.eval.pronostia_prep import PronostiaRunSequence
from edge.eval.pronostia_prognosis_targets import (
    TRAINING_BEARINGS_D025,
    compute_prognosis_targets,
)


def _sequence(n: int, bearing_id: str = "Bearing1_1") -> PronostiaRunSequence:
    """Minimal synthetic sequence -- only bearing_id and length matter for
    these tests; temperature/vibration/vibration_observed content is
    irrelevant to target generation and filled with inert placeholders."""
    return PronostiaRunSequence(
        bearing_id=bearing_id,
        operating_condition=1,
        split="training",
        timestamps=tuple((0, 0, i) for i in range(n)),
        temperature=tuple(20.0 for _ in range(n)),
        vibration=tuple(0.0 for _ in range(n)),
        vibration_observed=tuple(0.0 for _ in range(n)),
    )


# ---------------------------------------------------------------------------
# Output length / RUL sequence correctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 6, 10, 101])
def test_output_length_matches_input_length(n: int):
    targets = compute_prognosis_targets(_sequence(n))
    assert len(targets.rul_seconds) == n
    assert len(targets.health_state) == n


def test_exact_rul_sequence_for_n6():
    targets = compute_prognosis_targets(_sequence(6))
    assert targets.rul_seconds == (5.0, 4.0, 3.0, 2.0, 1.0, 0.0)


def test_rul_values_are_float():
    targets = compute_prognosis_targets(_sequence(6))
    assert all(isinstance(v, float) for v in targets.rul_seconds)


def test_final_timestep_rul_is_zero():
    targets = compute_prognosis_targets(_sequence(37))
    assert targets.rul_seconds[-1] == 0.0


def test_rul_decreases_monotonically_by_exactly_one_second():
    targets = compute_prognosis_targets(_sequence(50))
    diffs = [b - a for a, b in zip(targets.rul_seconds, targets.rul_seconds[1:], strict=False)]
    assert all(d == -1.0 for d in diffs)


# ---------------------------------------------------------------------------
# HealthState mapping
# ---------------------------------------------------------------------------


def test_healthstate_mapping_illustrative_fractions():
    # N=101 -> total_lifetime=100, so RUL/100 gives clean fractions.
    targets = compute_prognosis_targets(_sequence(101))
    # RUL=50 -> fraction=0.50 -> healthy
    assert targets.health_state[50] == HealthState.healthy
    # RUL=15 -> fraction=0.15 -> warning
    assert targets.health_state[85] == HealthState.warning
    # RUL=2 -> fraction=0.02 -> critical
    assert targets.health_state[98] == HealthState.critical


def test_healthstate_boundary_exactly_20_percent_is_warning():
    # N=101 -> total_lifetime=100 -> RUL=20 -> fraction=0.20 exactly.
    targets = compute_prognosis_targets(_sequence(101))
    idx_rul_20 = 100 - 20  # timestep whose RUL equals 20
    assert targets.rul_seconds[idx_rul_20] == 20.0
    assert targets.health_state[idx_rul_20] == HealthState.warning


def test_healthstate_boundary_just_above_20_percent_is_healthy():
    targets = compute_prognosis_targets(_sequence(101))
    idx_rul_21 = 100 - 21
    assert targets.rul_seconds[idx_rul_21] == 21.0
    assert targets.health_state[idx_rul_21] == HealthState.healthy


def test_healthstate_boundary_exactly_5_percent_is_critical():
    # N=101 -> total_lifetime=100 -> RUL=5 -> fraction=0.05 exactly.
    targets = compute_prognosis_targets(_sequence(101))
    idx_rul_5 = 100 - 5
    assert targets.rul_seconds[idx_rul_5] == 5.0
    assert targets.health_state[idx_rul_5] == HealthState.critical


def test_healthstate_boundary_just_above_5_percent_is_warning():
    targets = compute_prognosis_targets(_sequence(101))
    idx_rul_6 = 100 - 6
    assert targets.rul_seconds[idx_rul_6] == 6.0
    assert targets.health_state[idx_rul_6] == HealthState.warning


# ---------------------------------------------------------------------------
# Per-bearing (never global) lifetime denominator
# ---------------------------------------------------------------------------


def test_different_bearing_lengths_use_own_lifetime_denominator():
    """A short and a long bearing must each classify HealthState using
    THEIR OWN total lifetime, not a shared/global denominator."""
    short = compute_prognosis_targets(_sequence(11))  # total_lifetime=10
    long = compute_prognosis_targets(_sequence(1001))  # total_lifetime=1000

    # Short bearing: RUL=2 -> fraction=0.20 -> warning (boundary, inclusive).
    assert short.rul_seconds[10 - 2] == 2.0
    assert short.health_state[10 - 2] == HealthState.warning

    # Long bearing: RUL=2 -> fraction=0.002 -> critical (NOT warning, even
    # though the raw RUL value (2) is identical to the short bearing's --
    # proving the classification is proportion-based, not absolute-seconds-based).
    assert long.rul_seconds[1000 - 2] == 2.0
    assert long.health_state[1000 - 2] == HealthState.critical


def test_no_cross_bearing_state_leaks_between_calls():
    """Computing targets for one sequence must not affect the result for
    another -- pure function, no shared/global normalization or state."""
    first_call_short = compute_prognosis_targets(_sequence(11))
    compute_prognosis_targets(_sequence(1001))  # interleave a different bearing
    second_call_short = compute_prognosis_targets(_sequence(11))
    assert first_call_short == second_call_short


# ---------------------------------------------------------------------------
# Edge cases: N=1 and N=0
# ---------------------------------------------------------------------------


def test_n1_sequence_rul_zero_and_critical():
    targets = compute_prognosis_targets(_sequence(1))
    assert targets.rul_seconds == (0.0,)
    assert targets.health_state == (HealthState.critical,)


def test_empty_sequence_raises_value_error():
    empty = PronostiaRunSequence(
        bearing_id="Bearing1_1",
        operating_condition=1,
        split="training",
        timestamps=(),
        temperature=(),
        vibration=(),
        vibration_observed=(),
    )
    with pytest.raises(ValueError, match="empty sequence"):
        compute_prognosis_targets(empty)


# ---------------------------------------------------------------------------
# D025 bearing restriction: only the 4 usable training bearings
# ---------------------------------------------------------------------------


def test_training_bearings_constant_matches_d025():
    assert TRAINING_BEARINGS_D025 == {"Bearing1_1", "Bearing1_2", "Bearing2_1", "Bearing3_1"}


@pytest.mark.parametrize("bearing_id", ["Bearing1_1", "Bearing1_2", "Bearing2_1", "Bearing3_1"])
def test_all_four_d025_training_bearings_accepted(bearing_id: str):
    targets = compute_prognosis_targets(_sequence(6, bearing_id=bearing_id))
    assert len(targets.rul_seconds) == 6


@pytest.mark.parametrize(
    "bearing_id",
    ["Bearing1_4", "Bearing2_5", "Bearing3_3", "Bearing2_2", "NotABearing"],
)
def test_non_training_bearing_id_rejected(bearing_id: str):
    """Test-split bearings, excluded bearings, and malformed IDs must all
    be refused -- D025 authorizes exactly the 4 named training bearings."""
    with pytest.raises(ValueError, match="training bearings"):
        compute_prognosis_targets(_sequence(6, bearing_id=bearing_id))
