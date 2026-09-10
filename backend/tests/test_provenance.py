"""Provenance layer: sensor registry seeding + declaration reconciliation.

THE INVARIANT UNDER TEST, stated once:

    A TELEMETRY VALUE IS NEVER EVIDENCE OF PROVENANCE.

The frozen contract carries six plain floats. A placeholder constant of 1013.0
is byte-identical on the wire to a measured 1013.0, so no quantity, pattern or
volume of arriving data may promote a channel to "live". Only an explicit
declaration (SHTAPM_CHANNEL_SOURCES) combined with a registered part in the
Doc05 §05.2 `sensors` table can do that — and the tests below pin both halves.
"""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from app.api.devices import (  # noqa: E402
    _CHANNEL_NOTES,
    _DOCUMENTED_INTERFACES,
    resolve_channel_source,
)
from app.core.seed import _PUMP01_SENSORS, seed_sensor_registry  # noqa: E402
from app.models import Base, Device, Sensor  # noqa: E402
from app.schemas.contracts import CHANNELS  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db(session_factory):
    with session_factory() as session:
        session.add(Device(device_id="pump-01", name="Pump 01"))
        session.commit()
        yield session


def _rows(db) -> dict[str, Sensor]:
    return {
        r.channel.value if hasattr(r.channel, "value") else str(r.channel): r
        for r in db.query(Sensor).all()
    }


# ---------------------------------------------------------------------------
# Registry seeding
# ---------------------------------------------------------------------------


def test_seeds_all_six_frozen_channels(db):
    seed_sensor_registry(db)
    assert set(_rows(db)) == set(CHANNELS)


def test_seeds_the_documented_parts(db):
    seed_sensor_registry(db)
    rows = _rows(db)
    assert rows["temperature"].part == "DHT22"
    assert rows["humidity"].part == "DHT22"  # the SAME physical part (D028)
    assert rows["vibration"].part == "ADXL335"
    assert rows["pressure"].part == "BMP280"
    assert rows["current"].part == "INA219"


def test_gas_registers_no_part_because_none_is_documented(db):
    """No MQ-135 driver exists and no wiring is documented anywhere in this
    repository. The column is nullable so "we do not know" is representable;
    writing "MQ-135" would assert hardware nobody has established."""
    seed_sensor_registry(db)
    assert _rows(db)["gas"].part is None


def test_seeds_the_documented_units(db):
    seed_sensor_registry(db)
    rows = _rows(db)
    assert rows["temperature"].unit == "°C"
    assert rows["vibration"].unit == "g"
    assert rows["pressure"].unit == "hPa"
    assert rows["humidity"].unit == "%"
    assert rows["gas"].unit == "ppm"
    assert rows["current"].unit == "A"


def test_pressure_and_gas_are_flagged_as_proxies(db):
    """Doc05 §05.2: "pressure/gas = true (honest labelling)"."""
    seed_sensor_registry(db)
    rows = _rows(db)
    assert rows["pressure"].is_proxy is True
    assert rows["gas"].is_proxy is True
    for channel in ("temperature", "humidity", "vibration", "current"):
        assert rows[channel].is_proxy is False


def test_display_hue_is_never_written(db):
    """Doc04 asks for a per-channel hue but assigns none, so the seed has
    nothing truthful to put there."""
    seed_sensor_registry(db)
    assert all(row.display_hue is None for row in _rows(db).values())


def test_seeding_is_idempotent(db):
    first = seed_sensor_registry(db)
    second = seed_sensor_registry(db)
    assert len(first) == len(second) == len(CHANNELS)
    assert db.query(Sensor).count() == len(CHANNELS)  # UNIQUE(device_id, channel) honoured


def test_seeding_repairs_a_drifted_row_instead_of_duplicating(db):
    seed_sensor_registry(db)
    rows = _rows(db)
    rows["pressure"].part = "WRONG"
    rows["pressure"].is_proxy = False
    db.commit()

    seed_sensor_registry(db)
    repaired = _rows(db)["pressure"]
    assert repaired.part == "BMP280"
    assert repaired.is_proxy is True
    assert db.query(Sensor).count() == len(CHANNELS)


def test_seeding_preserves_an_operator_set_display_hue(db):
    seed_sensor_registry(db)
    row = _rows(db)["vibration"]
    row.display_hue = "--aurora-teal"
    db.commit()

    seed_sensor_registry(db)
    assert _rows(db)["vibration"].display_hue == "--aurora-teal"


def test_seeding_an_unknown_device_fails_loudly(db):
    """Silently creating the device would let a typo seed a registry that
    nothing ever reads."""
    with pytest.raises(RuntimeError, match="does not exist"):
        seed_sensor_registry(db, device_id="pump-99")


def test_registry_table_covers_exactly_the_frozen_channels():
    assert set(_PUMP01_SENSORS) == set(CHANNELS)


# ---------------------------------------------------------------------------
# Declaration ↔ registry reconciliation
# ---------------------------------------------------------------------------


def test_live_requires_both_a_declaration_and_a_registered_part():
    source, conflict = resolve_channel_source("live", "ADXL335")
    assert source == "live"
    assert conflict is None


def test_declared_live_with_no_registered_part_degrades_to_unknown():
    """The confident lie this prevents: a green LIVE badge over a constant,
    because someone declared a channel live that has nothing registered."""
    source, conflict = resolve_channel_source("live", None)
    assert source == "unknown"
    assert conflict is not None
    assert "no part is registered" in conflict


def test_placeholder_is_never_promoted_even_with_a_registered_part():
    source, conflict = resolve_channel_source("placeholder", "BMP280")
    assert source == "placeholder"
    assert conflict is None


def test_unknown_is_never_upgraded_by_registry_contents():
    """A fully populated registry row does not mean anything is plugged in.
    Nobody declared it, so nothing may be claimed."""
    source, _ = resolve_channel_source("unknown", "INA219")
    assert source == "unknown"


def test_proxy_status_does_not_block_live():
    """is_proxy is orthogonal to connectedness: a wired BMP280 genuinely
    measures, just not the quantity the channel name suggests. Conflating the
    two would make a connected proxy impossible to report honestly."""
    source, conflict = resolve_channel_source("live", "BMP280")
    assert source == "live"
    assert conflict is None


@pytest.mark.parametrize("declared", ["live", "placeholder", "unknown"])
def test_resolution_ignores_telemetry_entirely(declared):
    """resolve_channel_source has no parameter through which a value could
    enter. This asserts the shape of the function, not just its output."""
    import inspect

    params = set(inspect.signature(resolve_channel_source).parameters)
    assert params == {"declared", "registered_part"}
    assert resolve_channel_source(declared, "ADXL335")[0] in {"live", "placeholder", "unknown"}


# ---------------------------------------------------------------------------
# Documented interfaces and notes
# ---------------------------------------------------------------------------


def test_gas_has_no_documented_interface_for_any_part():
    """No ADC channel may ever be shown for gas."""
    assert not any(channel == "gas" for channel, _part in _DOCUMENTED_INTERFACES)


def test_vibration_interface_names_all_three_adc_channels():
    """ADXL335 is X/Y/Z across CH0-2; describing it as one channel would be
    wrong (edge/drivers/adxl335.py)."""
    interface = _DOCUMENTED_INTERFACES[("vibration", "ADXL335")]
    assert "CH0-2" in interface
    assert "SPI0 CE0" in interface


def test_temperature_and_humidity_share_one_documented_interface():
    assert _DOCUMENTED_INTERFACES[("temperature", "DHT22")] == "GPIO17"
    assert _DOCUMENTED_INTERFACES[("humidity", "DHT22")] == "GPIO17"


def test_interfaces_are_keyed_by_part_so_they_cannot_describe_another():
    """Looking up by channel alone would attach DHT22 wiring to whatever part
    happened to be registered."""
    assert ("temperature", "DS18B20") not in _DOCUMENTED_INTERFACES
    assert all(isinstance(key, tuple) and len(key) == 2 for key in _DOCUMENTED_INTERFACES)


def test_shared_sensor_note_is_stated_on_both_channels():
    for channel in ("temperature", "humidity"):
        assert "same physical DHT22" in _CHANNEL_NOTES[channel]
    assert "not" in _CHANNEL_NOTES["humidity"]  # "not independent corroboration"


def test_proxy_channels_explain_what_they_actually_measure():
    assert "not water-line" in _CHANNEL_NOTES["pressure"]
    assert "not H2S" in _CHANNEL_NOTES["gas"]


# ---------------------------------------------------------------------------
# Decision rows: what they carry, and what they must never imply
# ---------------------------------------------------------------------------


def test_decision_fields_nothing_computes_stay_null():
    """The diagnostic producer writes anomaly + trust and nothing else. These
    columns are UNIMPLEMENTED CAPABILITY, not missing data, and a UI must not
    render them as an assessed 'healthy' or an absent fault."""
    from app.services.decision_diagnostic_persistence import DecisionDiagnosticPersistence

    source = inspect_source(DecisionDiagnosticPersistence.persist)
    for never_written in (
        "health_state",
        "failure_eta",
        "rl_action",
        "isolated_channels",
        "substituted_channels",
    ):
        assert never_written not in source, (
            f"{never_written} is now written by the diagnostic path; the UI's "
            "'not computed' labelling must be revisited before this passes"
        )


def test_no_confidence_field_exists_anywhere_in_the_decision_schema():
    """Guards against a UI ever displaying a confidence number: there is no
    such value to display, and inventing one would misrepresent the model."""
    from app.api.devices import DecisionOut

    assert not any("confidence" in name for name in DecisionOut.model_fields)


def inspect_source(fn) -> str:
    import inspect as _inspect

    return _inspect.getsource(fn)
