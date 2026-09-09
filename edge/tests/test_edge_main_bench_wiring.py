"""Guards edge/main.py's ``_DEFAULT_CHANNEL_SPECS`` — the declarative table
that records which sensors are PHYSICALLY WIRED on this bench (P1 · C1).

This table is not a preference: a channel declared ``kind="real"`` whose
sensor is unplugged reads unhealthy forever, and ``Sampler.sample_once()``
requires all six channels healthy, so one wrong entry silently stops every
frame. Until now nothing pinned it — edge/tests/test_driver_registry.py's
``_default_specs()`` fixture exercises the registry MECHANISM with its own
representative table and drifted out of step with main.py as the bench was
reconfigured. These tests assert main.py's real table directly instead.

Hardware-free: real drivers are only CONSTRUCTED here, never read from.
Every real driver in this project opens its bus lazily on first read (see
each driver's own ``_open_*`` method), so constructing the exact bench
table proves it can't raise ``UnsupportedDriverError`` at boot without
needing a Pi, an SPI/I2C bus, or a 1-Wire probe.

Current bench state asserted below (2026-09-09): three real channels across
two sensors — DHT22 serving BOTH temperature (ambient air) and humidity, and
ADXL335 (vibration) — with pressure, gas and current fake constants. BMP280
is implemented and remains pressure's registered real driver, but is not
physically connected. When the bench is reconfigured, update this file WITH
main.py — a failure here means the two disagree.

Sourcing temperature from the DHT22 is the APPROVED project configuration
(supervisor decision, DECISIONS.md D028), not a stopgap. DS18B20 remains
registered as temperature's optional alternate, so the tests below assert
both the wiring AND that selecting that hardware later stays a one-line
change.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS

import edge.drivers.dht22_adafruit as dht22_adafruit_module
from edge.drivers.adxl335 import ADXL335Driver
from edge.drivers.base import Sensor, SensorDriver
from edge.drivers.bmp280 import BMP280Driver
from edge.drivers.dht22_adafruit import DHT22AdafruitDriver, DHT22AdafruitTemperatureDriver
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.registry import (
    DriverSpec,
    UnsupportedDriverError,
    build_drivers,
    resolve_channel_specs_from_env,
)
from edge.main import _DEFAULT_CHANNEL_SPECS

# The four physically-connected channels and the driver class each must
# resolve to. Mirrors this bench's actual wiring, not the set of drivers
# that happen to be implemented (INA219 is implemented but unplugged).
_EXPECTED_REAL: dict[str, type[SensorDriver]] = {
    "temperature": DHT22AdafruitTemperatureDriver,  # ambient air, shared DHT22 (D028)
    "vibration": ADXL335Driver,
    "humidity": DHT22AdafruitDriver,  # same physical sensor as temperature
}
_EXPECTED_FAKE_CONSTANTS = {"pressure": 1013.0, "gas": 150.0, "current": 0.0}


def test_default_specs_cover_exactly_the_frozen_channels():
    assert set(_DEFAULT_CHANNEL_SPECS) == set(CHANNELS)


def test_exactly_the_wired_channels_are_real():
    real = {ch for ch, spec in _DEFAULT_CHANNEL_SPECS.items() if spec.kind == "real"}
    assert real == set(_EXPECTED_REAL)


def test_temperature_and_humidity_are_served_by_the_one_shared_dht22():
    """D028's defining property: both channels come from a single physical
    sensor on GPIO17, through one shared reader — not two devices, and not a
    fake constant standing in for either."""
    drivers = build_drivers(_DEFAULT_CHANNEL_SPECS)
    assert isinstance(drivers["temperature"], DHT22AdafruitTemperatureDriver)
    assert isinstance(drivers["humidity"], DHT22AdafruitDriver)
    assert dht22_adafruit_module.shared_reader() is dht22_adafruit_module.shared_reader()


def test_unwired_channels_stay_fake_constants_at_their_documented_values():
    for channel, value in _EXPECTED_FAKE_CONSTANTS.items():
        spec = _DEFAULT_CHANNEL_SPECS[channel]
        assert spec.kind == "fake"
        assert spec.fake_mode == "constant"
        assert spec.params["value"] == value


def test_real_channels_declare_no_params_so_each_driver_uses_its_hardware_defaults():
    """DS18B20 auto-discovers its 28-<serial> sysfs device; BMP280 defaults to
    bus 1 / 0x76 (confirmed on this board); ADXL335 to SPI0 CE0 CH0-2; DHT22 to
    GPIO17. No bench-specific value is duplicated into main.py's table."""
    for channel in _EXPECTED_REAL:
        assert dict(_DEFAULT_CHANNEL_SPECS[channel].params) == {}


def test_bench_table_builds_the_expected_driver_objects_without_hardware():
    """The whole point: this exact table must construct at boot on the Pi."""
    drivers = build_drivers(_DEFAULT_CHANNEL_SPECS)

    assert set(drivers) == set(CHANNELS)
    for channel, expected_cls in _EXPECTED_REAL.items():
        assert isinstance(drivers[channel], expected_cls)
        assert not isinstance(drivers[channel], Sensor)  # real driver, not a fake
    for channel in _EXPECTED_FAKE_CONSTANTS:
        assert isinstance(drivers[channel], Sensor)


def test_gas_has_no_real_driver_so_it_can_never_be_flipped_real_by_mistake():
    """MQ-135 is unimplemented; a future edit flipping gas to real must fail
    loudly at construction, never fall back to fake silently."""
    specs = dict(_DEFAULT_CHANNEL_SPECS)
    specs["gas"] = _DEFAULT_CHANNEL_SPECS["vibration"]  # kind="real"
    with pytest.raises(UnsupportedDriverError):
        build_drivers(specs)


def test_a_disconnected_sensor_can_be_reverted_to_fake_by_env_without_a_code_edit():
    """If DS18B20 or BMP280 is unplugged again, SHTAPM_DRIVER_<CHANNEL>=fake
    restores a publishable bench without editing this table — the documented
    escape hatch (see edge/main.py's module docstring)."""
    resolved = resolve_channel_specs_from_env(
        _DEFAULT_CHANNEL_SPECS,
        env={"SHTAPM_DRIVER_TEMPERATURE": "fake", "SHTAPM_DRIVER_VIBRATION": "fake"},
    )
    for channel in ("temperature", "vibration"):
        assert resolved[channel].kind == "fake"
    assert resolved["humidity"].kind == "real"
    assert _DEFAULT_CHANNEL_SPECS["temperature"].kind == "real"  # not mutated


def test_adopting_the_ds18b20_alternate_is_a_one_line_change_not_a_redesign():
    """Guards main.py's docstring promise: DS18B20 is optional, not required,
    and adding that hardware later is one spec change — every other channel,
    and the frozen channel set, are untouched by it."""
    with_alternate = dict(_DEFAULT_CHANNEL_SPECS)
    with_alternate["temperature"] = DriverSpec(kind="alternate")

    drivers = build_drivers(with_alternate)

    assert isinstance(drivers["temperature"], DS18B20Driver)
    assert set(drivers) == set(CHANNELS)
    for channel, expected_cls in _EXPECTED_REAL.items():
        if channel == "temperature":
            continue  # deliberately replaced by the alternate in this scenario
        assert isinstance(drivers[channel], expected_cls)  # nothing else moved


def test_the_ds18b20_alternate_is_selectable_by_env_without_a_code_edit():
    resolved = resolve_channel_specs_from_env(
        _DEFAULT_CHANNEL_SPECS, env={"SHTAPM_DRIVER_TEMPERATURE": "alternate"}
    )
    assert resolved["temperature"] == DriverSpec(kind="alternate")
    assert _DEFAULT_CHANNEL_SPECS["temperature"].kind == "real"  # not mutated


def test_connecting_bmp280_later_is_a_one_line_change():
    """BMP280 is implemented and stays pressure's registered real driver while
    the sensor is unplugged, so wiring it up is flipping this one spec — the
    same promise made for every other channel on this bench."""
    connected = dict(_DEFAULT_CHANNEL_SPECS)
    connected["pressure"] = DriverSpec(kind="real")

    drivers = build_drivers(connected)

    assert isinstance(drivers["pressure"], BMP280Driver)
    assert set(drivers) == set(CHANNELS)
    for channel, expected_cls in _EXPECTED_REAL.items():
        assert isinstance(drivers[channel], expected_cls)  # nothing else moved
