"""Tests for edge/pipeline/prognosis_runtime.py (live prognosis wiring,
simulation-first). Mechanism-level only -- no test here claims meaningful
prognosis accuracy or real-world validation; see the module's own
docstring and edge/models/lstm_prognosis.py's.

hidden_size and every other numeric value below are TEST FIXTURES ONLY.

Skipped entirely when torch is unavailable -- same skip-pattern as
test_lstm_prognosis.py/test_self_heal.py's torch-dependent siblings.
"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

from app.schemas.contracts import CHANNELS, HealthState  # noqa: E402

from edge.anomaly.preprocess import Window  # noqa: E402
from edge.models.lstm_prognosis import LSTMPrognosisPredictor, _LSTMPrognosisNet  # noqa: E402
from edge.pipeline.prognosis_runtime import (  # noqa: E402
    EXECUTION_MODE,
    MODEL_STATUS,
    PrognosisResult,
    PrognosisRuntime,
)
from edge.trust.beta import classify  # noqa: E402
from edge.trust.engine import TrustReading  # noqa: E402

HIDDEN_SIZE_FIXTURE = 4
WINDOW_SIZE_FIXTURE = 30


def _window() -> Window:
    features = {ch: (0.0,) * WINDOW_SIZE_FIXTURE for ch in CHANNELS}
    return Window(start_index=0, end_index=WINDOW_SIZE_FIXTURE, features=features)


def _trust(overrides: dict[str, float] | None = None) -> dict[str, TrustReading]:
    overrides = overrides or {}
    return {
        ch: TrustReading(
            channel=ch, g=0.0, trust=overrides.get(ch, 1.0), band=classify(overrides.get(ch, 1.0))
        )
        for ch in CHANNELS
    }


def _runtime_with_predictor(prognosis_data_source: str = "synthetic") -> PrognosisRuntime:
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    predictor = LSTMPrognosisPredictor(network)
    return PrognosisRuntime(predictor=predictor, prognosis_data_source=prognosis_data_source)


# ---------------------------------------------------------------------------
# Valid prediction
# ---------------------------------------------------------------------------


def test_predict_returns_health_and_failure_eta_when_predictor_present():
    runtime = _runtime_with_predictor()
    result = runtime.predict(_window(), _trust())

    assert result.status == "ok"
    assert isinstance(result.health, HealthState)
    assert isinstance(result.failure_eta, float)


def test_all_channels_reported_available_by_default():
    runtime = _runtime_with_predictor()
    result = runtime.predict(_window(), _trust())

    assert result.availability == {ch: True for ch in CHANNELS}


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata_fields_present_and_correct():
    runtime = _runtime_with_predictor(prognosis_data_source="pronostia")
    result = runtime.predict(_window(), _trust())

    assert result.execution_mode == "simulation"
    assert result.model_status == "diagnostic_unvalidated"
    assert result.prognosis_data_source == "pronostia"
    assert (EXECUTION_MODE, MODEL_STATUS) == ("simulation", "diagnostic_unvalidated")


def test_health_label_source_defaults_to_none():
    runtime = _runtime_with_predictor()
    result = runtime.predict(_window(), _trust())
    assert result.health_label_source is None


def test_health_label_source_is_passed_through_when_supplied():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    runtime = PrognosisRuntime(
        predictor=LSTMPrognosisPredictor(network),
        prognosis_data_source="synthetic",
        health_label_source="synthetic_policy_fixture",
    )
    result = runtime.predict(_window(), _trust())
    assert result.health_label_source == "synthetic_policy_fixture"


def test_health_label_source_passed_through_from_checkpoint(tmp_path):
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    checkpoint_path = str(tmp_path / "diagnostic_checkpoint.pt")
    LSTMPrognosisPredictor(network).save(checkpoint_path)

    runtime = PrognosisRuntime.from_checkpoint(
        checkpoint_path,
        hidden_size=HIDDEN_SIZE_FIXTURE,
        prognosis_data_source="synthetic",
        health_label_source="synthetic_policy_fixture",
    )
    result = runtime.predict(_window(), _trust())
    assert result.health_label_source == "synthetic_policy_fixture"


def test_invalid_prognosis_data_source_raises():
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    with pytest.raises(ValueError, match="prognosis_data_source"):
        PrognosisRuntime(
            predictor=LSTMPrognosisPredictor(network), prognosis_data_source="pump_bench_validated"
        )


def test_synthetic_and_pronostia_labels_are_never_conflated():
    synthetic_result = _runtime_with_predictor("synthetic").predict(_window(), _trust())
    pronostia_result = _runtime_with_predictor("pronostia").predict(_window(), _trust())
    assert synthetic_result.prognosis_data_source == "synthetic"
    assert pronostia_result.prognosis_data_source == "pronostia"
    assert synthetic_result.prognosis_data_source != pronostia_result.prognosis_data_source


# ---------------------------------------------------------------------------
# Graceful degradation: no predictor / missing checkpoint
# ---------------------------------------------------------------------------


def test_predict_with_no_predictor_returns_predictor_unavailable_status():
    runtime = PrognosisRuntime(predictor=None, prognosis_data_source="synthetic")
    result = runtime.predict(_window(), _trust())

    assert result.status == "predictor_unavailable"
    assert result.health is None
    assert result.failure_eta is None
    assert isinstance(result, PrognosisResult)


def test_predict_with_no_predictor_still_reports_availability():
    runtime = PrognosisRuntime(predictor=None, prognosis_data_source="synthetic")
    result = runtime.predict(_window(), _trust(), unavailable_channels={"vibration"})

    assert result.status == "predictor_unavailable"
    assert result.availability["vibration"] is False
    assert result.availability["temperature"] is True


def test_from_checkpoint_missing_file_degrades_gracefully(tmp_path):
    missing_path = str(tmp_path / "no_such_checkpoint.pt")
    runtime = PrognosisRuntime.from_checkpoint(
        missing_path, hidden_size=HIDDEN_SIZE_FIXTURE, prognosis_data_source="synthetic"
    )
    result = runtime.predict(_window(), _trust())

    assert result.status == "predictor_unavailable"


def test_from_checkpoint_existing_file_loads_a_working_predictor(tmp_path):
    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    checkpoint_path = str(tmp_path / "diagnostic_checkpoint.pt")
    LSTMPrognosisPredictor(network).save(checkpoint_path)

    runtime = PrognosisRuntime.from_checkpoint(
        checkpoint_path, hidden_size=HIDDEN_SIZE_FIXTURE, prognosis_data_source="synthetic"
    )
    result = runtime.predict(_window(), _trust())

    assert result.status == "ok"


# ---------------------------------------------------------------------------
# Isolated / unavailable channels
# ---------------------------------------------------------------------------


def test_isolated_channel_does_not_crash_prediction():
    runtime = _runtime_with_predictor()
    result = runtime.predict(
        _window(), _trust({"vibration": 0.0}), unavailable_channels={"vibration"}
    )

    assert result.status == "ok"
    assert result.availability["vibration"] is False


def test_all_non_temperature_channels_unavailable_does_not_crash():
    runtime = _runtime_with_predictor()
    unavailable = set(CHANNELS[1:])
    result = runtime.predict(_window(), _trust(), unavailable_channels=unavailable)

    assert result.status == "ok"
    assert all(result.availability[ch] is False for ch in unavailable)
    assert result.availability["temperature"] is True


def test_temperature_marked_unavailable_is_reported_but_does_not_crash():
    """D022/D024 has no model-input availability column for temperature --
    naming it must still be honestly reported, never raise."""
    runtime = _runtime_with_predictor()
    result = runtime.predict(_window(), _trust(), unavailable_channels={"temperature"})

    assert result.status == "ok"
    assert result.availability["temperature"] is False


def test_temperature_unavailable_reports_the_documented_limitation():
    runtime = _runtime_with_predictor()
    result = runtime.predict(_window(), _trust(), unavailable_channels={"temperature"})

    assert result.temperature_availability_limitation is not None
    assert "trust" in result.temperature_availability_limitation


def test_temperature_available_reports_no_limitation():
    runtime = _runtime_with_predictor()
    result = runtime.predict(_window(), _trust())

    assert result.temperature_availability_limitation is None


def test_temperature_limitation_reported_even_when_predictor_unavailable():
    runtime = PrognosisRuntime(predictor=None, prognosis_data_source="synthetic")
    result = runtime.predict(_window(), _trust(), unavailable_channels={"temperature"})

    assert result.status == "predictor_unavailable"
    assert result.temperature_availability_limitation is not None


def test_temperature_unavailable_does_not_mutate_callers_trust_mapping():
    runtime = _runtime_with_predictor()
    trust = _trust()
    original_temperature_reading = trust["temperature"]

    runtime.predict(_window(), trust, unavailable_channels={"temperature"})

    assert trust["temperature"] is original_temperature_reading
    assert trust["temperature"].trust == 1.0


def test_temperature_unavailable_changes_effective_model_input():
    """Forcing temperature's effective trust to 0.0 must actually change
    what the model sees whenever temperature's own raw value is nonzero --
    proving the fix is a real input change, not just a reported label."""
    features = {ch: (0.0,) * WINDOW_SIZE_FIXTURE for ch in CHANNELS}
    features["temperature"] = (50.0,) * WINDOW_SIZE_FIXTURE
    window = Window(start_index=0, end_index=WINDOW_SIZE_FIXTURE, features=features)

    network = _LSTMPrognosisNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    runtime = PrognosisRuntime(
        predictor=LSTMPrognosisPredictor(network), prognosis_data_source="synthetic"
    )

    available_result = runtime.predict(window, _trust())
    unavailable_result = runtime.predict(window, _trust(), unavailable_channels={"temperature"})

    assert available_result.failure_eta != pytest.approx(unavailable_result.failure_eta)


def test_unknown_channel_in_unavailable_channels_raises():
    runtime = _runtime_with_predictor()
    with pytest.raises(ValueError, match="unknown channel"):
        runtime.predict(_window(), _trust(), unavailable_channels={"not_a_channel"})


# ---------------------------------------------------------------------------
# Structural isolation: no hardware/network/actuator coupling, no
# over-claimed validation
# ---------------------------------------------------------------------------


def test_module_has_no_hardware_network_or_actuator_imports():
    import edge.pipeline.prognosis_runtime as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    forbidden_names = (
        "RPi",
        "gpiozero",
        "paho",
        "RelayController",
        "FakeActuator",
        "SelfHealOrchestrator",
    )
    for forbidden in forbidden_names:
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


def test_module_never_claims_hardware_or_field_validation():
    import edge.pipeline.prognosis_runtime as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "hardware-validated" not in content
    assert "field-validated" not in content
    assert "production-ready" not in content
