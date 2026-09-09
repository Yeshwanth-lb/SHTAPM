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

Current bench state asserted below (2026-09-09): DS18B20 (temperature),
ADXL335 (vibration), BMP280 (pressure) and DHT22 (humidity) real; gas and
current fake constants. When the bench is reconfigured again, update this
file WITH main.py — a failure here means the two disagree.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS

from edge.drivers.adxl335 import ADXL335Driver
from edge.drivers.base import Sensor, SensorDriver
from edge.drivers.bmp280 import BMP280Driver
from edge.drivers.dht22_adafruit import DHT22AdafruitDriver
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.registry import (
    UnsupportedDriverError,
    build_drivers,
    resolve_channel_specs_from_env,
)
from edge.main import _DEFAULT_CHANNEL_SPECS

# The four physically-connected channels and the driver class each must
# resolve to. Mirrors this bench's actual wiring, not the set of drivers
# that happen to be implemented (INA219 is implemented but unplugged).
_EXPECTED_REAL: dict[str, type[SensorDriver]] = {
    "temperature": DS18B20Driver,
    "vibration": ADXL335Driver,
    "pressure": BMP280Driver,
    "humidity": DHT22AdafruitDriver,
}
_EXPECTED_FAKE_CONSTANTS = {"gas": 150.0, "current": 0.0}


def test_default_specs_cover_exactly_the_frozen_channels():
    assert set(_DEFAULT_CHANNEL_SPECS) == set(CHANNELS)


def test_exactly_the_four_wired_channels_are_real():
    real = {ch for ch, spec in _DEFAULT_CHANNEL_SPECS.items() if spec.kind == "real"}
    assert real == set(_EXPECTED_REAL)


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
        env={"SHTAPM_DRIVER_TEMPERATURE": "fake", "SHTAPM_DRIVER_PRESSURE": "fake"},
    )
    for channel in ("temperature", "pressure"):
        assert resolved[channel].kind == "fake"
    for channel in ("vibration", "humidity"):
        assert resolved[channel].kind == "real"
    assert _DEFAULT_CHANNEL_SPECS["temperature"].kind == "real"  # not mutated
