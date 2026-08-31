"""Tests for edge/models/lstm_prognosis.py (P3 prognosis skeleton, hardware-
free ARCHITECTURE/PLUMBING development ONLY, D016/D022/D024).

No test here claims, or should be read as claiming, meaningful health-state
classification, ETA quality, or real-world validation of FR-M1/M2.
hidden_size and every other numeric value below are TEST FIXTURES ONLY,
never project specs. There is no training test, no dataset, and no
accuracy/classification/ETA-quality assertion anywhere in this file --
none of that exists yet (see edge/models/lstm_prognosis.py's module
docstring and DECISIONS.md D017).

No Protocol-conformance test: edge/models/lstm_prognosis.py deliberately
does not introduce a PrognosisPredictor Protocol (no P3 code currently
consumes one -- see that module's docstring).

Skipped entirely when torch is unavailable -- same skip-pattern as
test_lstm_twin.py.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402
from app.schemas.contracts import CHANNELS, HealthState  # noqa: E402

from edge.anomaly.preprocess import Window  # noqa: E402
from edge.models.lstm_prognosis import (  # noqa: E402
    _AVAILABILITY_CHANNELS_D024,
    PROGNOSIS_INPUT_WIDTH_D024,
    LSTMPrognosisPredictor,
    _LSTMPrognosisNet,
    build_prognosis_input,
)
from edge.trust.beta import classify  # noqa: E402
from edge.trust.engine import TrustReading  # noqa: E402

HIDDEN_SIZE_FIXTURE = 4
WINDOW_SIZE_FIXTURE = 30


def _window(values_by_channel: dict[str, float]) -> Window:
    """30-sample window; each named channel is constant across all 30
    samples (unnamed channels default to 0.0) -- same fixture shape as
    test_lstm_twin.py."""
    features = {
        ch: tuple(float(values_by_channel.get(ch, 0.0)) for _ in range(WINDOW_SIZE_FIXTURE))
        for ch in CHANNELS
    }
    return Window(start_index=0, end_index=WINDOW_SIZE_FIXTURE, features=features)


def _trust(overrides: dict[str, float]) -> dict[str, TrustReading]:
    """All channels default to trust=1.0 unless overridden."""
    return {
        ch: TrustReading(
            channel=ch, g=0.0, trust=overrides.get(ch, 1.0), band=classify(overrides.get(ch, 1.0))
        )
        for ch in CHANNELS
    }


def _availability(overrides: dict[str, tuple] | None = None) -> dict[str, tuple[float, ...]]:
    """All D022/D024 availability-indicator channels default to
    fully-observed (1.0 at every timestep) unless overridden with an
    explicit per-timestep sequence. Never derived from/coupled to trust."""
    overrides = overrides or {}
    return {
        ch: overrides.get(ch, tuple(1.0 for _ in range(WINDOW_SIZE_FIXTURE)))
        for ch in _AVAILABILITY_CHANNELS_D024
    }


# ---------------------------------------------------------------------------
# build_prognosis_input
# ---------------------------------------------------------------------------


def test_build_prognosis_input_shape():
    window = _window({})
    tensor = build_prognosis_input(window, _trust({}), _availability())
    assert tensor.shape == (1, WINDOW_SIZE_FIXTURE, PROGNOSIS_INPUT_WIDTH_D024)
    assert PROGNOSIS_INPUT_WIDTH_D024 == 11


def test_trust_weighting_scales_values():
    window = _window({"temperature": 10.0})
    tensor = build_prognosis_input(window, _trust({"temperature": 0.5}), _availability())
    temp_index = CHANNELS.index("temperature")
    assert torch.allclose(tensor[0, :, temp_index], torch.full((30,), 5.0))


def test_trust_zero_removes_channel_contribution():
    """Core invariant: trust=0 for a channel must zero every one of that
    channel's values in the built tensor, regardless of the channel's raw
    reading."""
    window = _window({"vibration": 999.0})
    tensor = build_prognosis_input(window, _trust({"vibration": 0.0}), _availability())
    vib_index = CHANNELS.index("vibration")
    assert torch.all(tensor[0, :, vib_index] == 0.0)


def test_build_prognosis_input_raises_on_missing_trust_channel():
    window = _window({})
    trust = _trust({})
    del trust["gas"]
    with pytest.raises(ValueError):
        build_prognosis_input(window, trust, _availability())


def test_build_prognosis_input_raises_on_missing_availability_channel():
    window = _window({})
    availability = _availability()
    del availability["vibration"]
    with pytest.raises(ValueError):
        build_prognosis_input(window, _trust({}), availability)


# ---------------------------------------------------------------------------
# D022/D024: exact 11-column width and ordering
# ---------------------------------------------------------------------------


def test_column_order_matches_channels_then_five_availability_indicators():
    """Columns 0-5 = CHANNELS in order; columns 6-10 = vibration_observed,
    pressure_observed, humidity_observed, gas_observed, current_observed."""
    values_by_channel = {
        "temperature": 1.0,
        "vibration": 2.0,
        "pressure": 3.0,
        "humidity": 4.0,
        "gas": 5.0,
        "current": 6.0,
    }
    window = _window(values_by_channel)
    availability = _availability(
        {
            "vibration": tuple(0.1 for _ in range(WINDOW_SIZE_FIXTURE)),
            "pressure": tuple(0.2 for _ in range(WINDOW_SIZE_FIXTURE)),
            "humidity": tuple(0.3 for _ in range(WINDOW_SIZE_FIXTURE)),
            "gas": tuple(0.4 for _ in range(WINDOW_SIZE_FIXTURE)),
            "current": tuple(0.5 for _ in range(WINDOW_SIZE_FIXTURE)),
        }
    )
    tensor = build_prognosis_input(window, _trust({}), availability)

    expected = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    for col, value in enumerate(expected):
        assert tensor[0, 0, col].item() == pytest.approx(value), f"column {col}"


# ---------------------------------------------------------------------------
# D022: vibration_observed behavior
# ---------------------------------------------------------------------------


def test_observed_vibration_carries_real_value_and_indicator_one():
    window = _window({"vibration": 7.5})
    availability = _availability({"vibration": tuple(1.0 for _ in range(WINDOW_SIZE_FIXTURE))})
    tensor = build_prognosis_input(window, _trust({}), availability)

    vib_index = CHANNELS.index("vibration")
    vib_observed_index = len(CHANNELS) + _AVAILABILITY_CHANNELS_D024.index("vibration")
    assert tensor[0, 0, vib_index].item() == pytest.approx(7.5)
    assert tensor[0, 0, vib_observed_index].item() == pytest.approx(1.0)


def test_unobserved_vibration_is_zero_value_and_indicator_zero():
    window = _window({"vibration": 0.0})
    availability = _availability({"vibration": tuple(0.0 for _ in range(WINDOW_SIZE_FIXTURE))})
    tensor = build_prognosis_input(window, _trust({}), availability)

    vib_index = CHANNELS.index("vibration")
    vib_observed_index = len(CHANNELS) + _AVAILABILITY_CHANNELS_D024.index("vibration")
    assert tensor[0, 0, vib_index].item() == pytest.approx(0.0)
    assert tensor[0, 0, vib_observed_index].item() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# D024: the four unavailable channels
# ---------------------------------------------------------------------------


_UNAVAILABLE_D024_CHANNELS = ("pressure", "humidity", "gas", "current")


def test_all_four_unavailable_channels_are_zero_value_and_zero_indicator():
    window = _window({})  # pressure/humidity/gas/current default to 0.0
    zeros = tuple(0.0 for _ in range(WINDOW_SIZE_FIXTURE))
    availability = _availability({ch: zeros for ch in _UNAVAILABLE_D024_CHANNELS})
    tensor = build_prognosis_input(window, _trust({}), availability)

    for ch in _UNAVAILABLE_D024_CHANNELS:
        raw_index = CHANNELS.index(ch)
        observed_index = len(CHANNELS) + _AVAILABILITY_CHANNELS_D024.index(ch)
        assert tensor[0, 0, raw_index].item() == pytest.approx(0.0), f"{ch} raw value"
        assert tensor[0, 0, observed_index].item() == pytest.approx(0.0), f"{ch} indicator"


# ---------------------------------------------------------------------------
# Indicator, not value, distinguishes "unavailable" from a genuine zero
# ---------------------------------------------------------------------------


def test_genuine_zero_vibration_distinguishable_from_unavailable_by_indicator_only():
    """A real, trusted vibration reading of exactly 0.0 (indicator=1.0) must
    be numerically identical, in its raw column, to an unavailable vibration
    slot (indicator=0.0) -- the indicator column is the ONLY thing that
    distinguishes them."""
    window = _window({"vibration": 0.0})
    observed = tuple(1.0 for _ in range(WINDOW_SIZE_FIXTURE))
    unobserved = tuple(0.0 for _ in range(WINDOW_SIZE_FIXTURE))

    genuine_zero = build_prognosis_input(window, _trust({}), _availability({"vibration": observed}))
    unavailable = build_prognosis_input(
        window, _trust({}), _availability({"vibration": unobserved})
    )

    vib_index = CHANNELS.index("vibration")
    vib_observed_index = len(CHANNELS) + _AVAILABILITY_CHANNELS_D024.index("vibration")

    # Raw value columns are identical -- both 0.0.
    genuine_zero_raw = genuine_zero[0, 0, vib_index].item()
    unavailable_raw = unavailable[0, 0, vib_index].item()
    assert genuine_zero_raw == unavailable_raw == pytest.approx(0.0)
    # Only the indicator column differs.
    assert genuine_zero[0, 0, vib_observed_index].item() == pytest.approx(1.0)
    assert unavailable[0, 0, vib_observed_index].item() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Trust and availability are independent
# ---------------------------------------------------------------------------


def test_trust_and_availability_vary_independently():
    window = _window({"vibration": 4.0})
    observed = tuple(1.0 for _ in range(WINDOW_SIZE_FIXTURE))
    unobserved = tuple(0.0 for _ in range(WINDOW_SIZE_FIXTURE))

    # Low trust, fully available: raw column reflects trust; indicator stays 1.0.
    low_trust = build_prognosis_input(
        window, _trust({"vibration": 0.1}), _availability({"vibration": observed})
    )
    # Full trust, unavailable: raw column unaffected by availability; indicator is 0.0.
    unavailable_but_trusted = build_prognosis_input(
        window, _trust({"vibration": 1.0}), _availability({"vibration": unobserved})
    )

    vib_index = CHANNELS.index("vibration")
    vib_observed_index = len(CHANNELS) + _AVAILABILITY_CHANNELS_D024.index("vibration")

    assert low_trust[0, 0, vib_index].item() == pytest.approx(0.4)  # 4.0 * 0.1
    assert low_trust[0, 0, vib_observed_index].item() == pytest.approx(1.0)

    assert unavailable_but_trusted[0, 0, vib_index].item() == pytest.approx(4.0)  # 4.0 * 1.0
    assert unavailable_but_trusted[0, 0, vib_observed_index].item() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _LSTMPrognosisNet / LSTMPrognosisPredictor
# ---------------------------------------------------------------------------


def test_hidden_size_has_no_default_on_net_and_predictor():
    sig_net = inspect.signature(_LSTMPrognosisNet.__init__)
    assert sig_net.parameters["hidden_size"].default is inspect.Parameter.empty
    sig_predictor = inspect.signature(LSTMPrognosisPredictor.__init__)
    assert sig_predictor.parameters["network"].default is inspect.Parameter.empty


def test_availability_has_no_default_on_build_prognosis_input_and_predict():
    sig_builder = inspect.signature(build_prognosis_input)
    assert sig_builder.parameters["availability"].default is inspect.Parameter.empty
    sig_predict = inspect.signature(LSTMPrognosisPredictor.predict)
    assert sig_predict.parameters["availability"].default is inspect.Parameter.empty


def test_network_forward_output_shapes():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    window = _window({"temperature": 0.5})
    tensor = build_prognosis_input(window, _trust({}), _availability())
    health_logits, eta = network(tensor)
    assert health_logits.shape == (1, 3)
    assert eta.shape == (1, 1)


def test_eleven_wide_tensor_passes_through_model_successfully():
    """End-to-end: the 11-wide D022/D024 tensor flows through the network
    without error and produces well-formed outputs."""
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    window = _window({"temperature": 0.5, "vibration": 1.2})
    availability = _availability({"vibration": tuple(1.0 for _ in range(WINDOW_SIZE_FIXTURE))})
    tensor = build_prognosis_input(window, _trust({}), availability)

    assert tensor.shape[-1] == PROGNOSIS_INPUT_WIDTH_D024
    health_logits, eta = network(tensor)
    assert health_logits.shape == (1, 3)
    assert eta.shape == (1, 1)
    assert bool(torch.isfinite(eta).all())


def test_predict_returns_valid_health_state_and_finite_eta():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    predictor = LSTMPrognosisPredictor(network)
    window = _window({"temperature": 0.5})
    health, eta = predictor.predict(window, _trust({}), _availability())
    assert isinstance(health, HealthState)
    assert isinstance(eta, float)
    assert eta == eta  # not NaN
    assert eta not in (float("inf"), float("-inf"))


def test_predict_is_deterministic_in_eval_mode():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    predictor = LSTMPrognosisPredictor(network)
    window = _window({"temperature": 0.5})
    trust = _trust({})
    availability = _availability()
    first = predictor.predict(window, trust, availability)
    second = predictor.predict(window, trust, availability)
    assert first == second


def test_save_and_from_checkpoint_round_trip(tmp_path):
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    predictor = LSTMPrognosisPredictor(network)
    window = _window({"temperature": 0.5})
    trust = _trust({})
    availability = _availability()
    before = predictor.predict(window, trust, availability)

    checkpoint_path = tmp_path / "prognosis.pt"
    predictor.save(str(checkpoint_path))
    reloaded = LSTMPrognosisPredictor.from_checkpoint(
        str(checkpoint_path), hidden_size=HIDDEN_SIZE_FIXTURE
    )
    after = reloaded.predict(window, trust, availability)

    assert before == after
