"""Tests for edge/eval/pronostia_prognosis_input.py (P3 PRONOSTIA -> prognosis
glue, D022/D023/D024).

Uses small SYNTHETIC PronostiaRunSequence fixtures only -- never the real
~1.1GB downloaded dataset. Loader-level testing (real raw-CSV parsing,
D023 treatments) remains the responsibility of test_pronostia_prep.py; this
file tests only the glue mapping from an already-built PronostiaRunSequence
to the 11-column prognosis input tensor.
"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

from app.schemas.contracts import CHANNELS  # noqa: E402

from edge.eval.pronostia_prep import PronostiaRunSequence  # noqa: E402
from edge.eval.pronostia_prognosis_input import (  # noqa: E402
    pronostia_sequence_to_prognosis_input,
)
from edge.trust.beta import classify  # noqa: E402
from edge.trust.engine import TrustReading  # noqa: E402


def _sequence(
    n: int,
    temperature: tuple[float, ...] | None = None,
    vibration: tuple[float, ...] | None = None,
    vibration_observed: tuple[float, ...] | None = None,
) -> PronostiaRunSequence:
    return PronostiaRunSequence(
        bearing_id="Bearing1_1",
        operating_condition=1,
        split="training",
        timestamps=tuple((0, 0, i) for i in range(n)),
        temperature=temperature or tuple(20.0 + i for i in range(n)),
        vibration=vibration or tuple(0.0 for _ in range(n)),
        vibration_observed=vibration_observed or tuple(0.0 for _ in range(n)),
    )


def _trust(
    value: float = 1.0, overrides: dict[str, float] | None = None
) -> dict[str, TrustReading]:
    overrides = overrides or {}
    return {
        ch: TrustReading(
            channel=ch,
            g=0.0,
            trust=overrides.get(ch, value),
            band=classify(overrides.get(ch, value)),
        )
        for ch in CHANNELS
    }


# ---------------------------------------------------------------------------
# Shape and column order
# ---------------------------------------------------------------------------


def test_output_shape_is_exactly_1_n_11():
    seq = _sequence(5)
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust())
    assert tensor.shape == (1, 5, 11)


def test_column_order_matches_d022_d024_contract():
    seq = _sequence(
        3,
        temperature=(10.0, 11.0, 12.0),
        vibration=(1.0, 2.0, 3.0),
        vibration_observed=(1.0, 0.0, 1.0),
    )
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust())

    # timestep 0: temperature=10, vibration=1, pressure/humidity/gas/current=0,
    # vibration_observed=1, four D024 indicators=0
    expected_t0 = [10.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    for col, value in enumerate(expected_t0):
        assert tensor[0, 0, col].item() == pytest.approx(value), f"column {col}"


# ---------------------------------------------------------------------------
# Pass-through of real PRONOSTIA data
# ---------------------------------------------------------------------------


def test_temperature_passes_through_unchanged_when_trust_is_one():
    seq = _sequence(4, temperature=(1.1, 2.2, 3.3, 4.4))
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust(1.0))
    temp_index = CHANNELS.index("temperature")
    for t, expected in enumerate(seq.temperature):
        assert tensor[0, t, temp_index].item() == pytest.approx(expected)


def test_vibration_passes_through_unchanged_when_trust_is_one():
    seq = _sequence(4, vibration=(5.5, 6.6, 7.7, 8.8))
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust(1.0))
    vib_index = CHANNELS.index("vibration")
    for t, expected in enumerate(seq.vibration):
        assert tensor[0, t, vib_index].item() == pytest.approx(expected)


def test_vibration_observed_passes_through_unchanged():
    seq = _sequence(5, vibration_observed=(1.0, 0.0, 1.0, 1.0, 0.0))
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust())
    vib_observed_index = CHANNELS.index("vibration") + 5  # column 6
    for t, expected in enumerate(seq.vibration_observed):
        assert tensor[0, t, vib_observed_index].item() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# The four D024 unavailable channels
# ---------------------------------------------------------------------------


_UNAVAILABLE_CHANNELS = ("pressure", "humidity", "gas", "current")


def test_four_unavailable_raw_channels_are_exactly_zero():
    seq = _sequence(6)
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust())
    for ch in _UNAVAILABLE_CHANNELS:
        idx = CHANNELS.index(ch)
        assert bool((tensor[0, :, idx] == 0.0).all()), f"{ch} raw values"


def test_four_unavailable_indicators_are_exactly_zero():
    seq = _sequence(6)
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust())
    # Columns 7-10, in CHANNELS[1:] order: vibration(6), pressure(7),
    # humidity(8), gas(9), current(10).
    for offset, ch in enumerate(("pressure", "humidity", "gas", "current"), start=7):
        assert bool((tensor[0, :, offset] == 0.0).all()), f"{ch} indicator"


# ---------------------------------------------------------------------------
# Trust vs. availability independence
# ---------------------------------------------------------------------------


def test_availability_unaffected_by_arbitrary_trust_including_zero():
    seq = _sequence(4, vibration_observed=(1.0, 0.0, 1.0, 0.0))
    tensor_full_trust = pronostia_sequence_to_prognosis_input(seq, _trust(1.0))
    tensor_zero_trust = pronostia_sequence_to_prognosis_input(seq, _trust(0.0))

    vib_observed_index = 6
    for t in range(4):
        assert (
            tensor_full_trust[0, t, vib_observed_index].item()
            == tensor_zero_trust[0, t, vib_observed_index].item()
            == pytest.approx(seq.vibration_observed[t])
        )


def test_trust_weighting_affects_only_six_raw_columns_never_availability():
    seq = _sequence(3, temperature=(10.0, 10.0, 10.0), vibration_observed=(1.0, 1.0, 1.0))
    tensor = pronostia_sequence_to_prognosis_input(
        seq, _trust(1.0, overrides={"temperature": 0.5, "vibration": 0.0})
    )

    temp_index = CHANNELS.index("temperature")
    vib_index = CHANNELS.index("vibration")
    assert tensor[0, 0, temp_index].item() == pytest.approx(5.0)  # 10.0 * 0.5
    assert tensor[0, 0, vib_index].item() == pytest.approx(0.0)  # trust=0

    # Availability columns (6-10) are untouched by trust.
    for offset in range(6, 11):
        expected = 1.0 if offset == 6 else 0.0  # only vibration_observed is 1.0 here
        assert tensor[0, 0, offset].item() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# No interpolation/smoothing
# ---------------------------------------------------------------------------


def test_unobserved_vibration_timestep_stays_zero_no_interpolation():
    """A vibration_observed=0 timestep, sandwiched between real bursts, must
    remain exactly 0.0/0.0 -- not smoothed/averaged from its neighbors."""
    seq = _sequence(
        3,
        vibration=(5.0, 0.0, 7.0),
        vibration_observed=(1.0, 0.0, 1.0),
    )
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust())
    vib_index = CHANNELS.index("vibration")

    assert tensor[0, 0, vib_index].item() == pytest.approx(5.0)
    assert tensor[0, 1, vib_index].item() == pytest.approx(0.0)  # not e.g. 6.0 (average)
    assert tensor[0, 2, vib_index].item() == pytest.approx(7.0)
    assert tensor[0, 0, 6].item() == pytest.approx(1.0)
    assert tensor[0, 1, 6].item() == pytest.approx(0.0)
    assert tensor[0, 2, 6].item() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Sequence length preservation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 3, 10])
def test_sequence_length_preserved(n: int):
    seq = _sequence(n)
    tensor = pronostia_sequence_to_prognosis_input(seq, _trust())
    assert tensor.shape[1] == n


# ---------------------------------------------------------------------------
# Error propagation -- not swallowed or replaced
# ---------------------------------------------------------------------------


def test_missing_trust_channel_raises_build_prognosis_input_error():
    seq = _sequence(3)
    trust = _trust()
    del trust["gas"]
    with pytest.raises(ValueError, match="gas"):
        pronostia_sequence_to_prognosis_input(seq, trust)
