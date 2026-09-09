"""Tests for edge/drivers/registry.py -- the configuration-driven
sensor-driver registry. See its own module docstring for the design:
real- and fake-driver construction are separate code paths, an
unsupported/unavailable choice fails clearly (UnsupportedDriverError),
and existing behavior is preserved whenever no new configuration is
supplied.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS

from edge.drivers.adxl335 import ADXL335Driver
from edge.drivers.base import Sensor, SensorDriver
from edge.drivers.bmp280 import BMP280Driver
from edge.drivers.dht22_adafruit import DHT22AdafruitDriver
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.ina219 import INA219Driver
from edge.drivers.registry import (
    DriverSpec,
    UnsupportedDriverError,
    build_driver,
    build_drivers,
    resolve_channel_specs_from_env,
)


def _fixed_clock() -> str:
    return "2026-01-01T00:00:00.000Z"


def _default_specs() -> dict[str, DriverSpec]:
    """A representative one-real/five-fake table for exercising the registry
    MECHANISM (build_drivers + env resolution). Deliberately NOT a mirror of
    edge/main.py's _DEFAULT_CHANNEL_SPECS: the bench's real wiring changes,
    and these mechanism tests should not churn with it. main.py's own table
    is asserted directly in test_edge_main_bench_wiring.py."""
    return {
        "temperature": DriverSpec(kind="real"),
        "vibration": DriverSpec(kind="fake", fake_mode="constant", params={"value": 0.03}),
        "pressure": DriverSpec(kind="fake", fake_mode="constant", params={"value": 1013.0}),
        "humidity": DriverSpec(kind="fake", fake_mode="constant", params={"value": 45.0}),
        "gas": DriverSpec(kind="fake", fake_mode="constant", params={"value": 150.0}),
        "current": DriverSpec(kind="fake", fake_mode="constant", params={"value": 0.0}),
    }


# ---------------------------------------------------------------------------
# Fake driver selection
# ---------------------------------------------------------------------------


def test_registry_selects_constant_fake_driver():
    driver = build_driver(
        "pressure", DriverSpec(kind="fake", fake_mode="constant", params={"value": 42.0})
    )
    assert isinstance(driver, Sensor)
    r = driver.read()
    assert r.healthy is True and r.value == 42.0


def test_registry_selects_realistic_fake_driver():
    spec = DriverSpec(
        kind="fake",
        fake_mode="realistic",
        params={"baseline": 10.0, "noise_std": 0.1, "drift_std": 0.01, "seed": 123},
    )
    driver = build_driver("temperature", spec)
    assert isinstance(driver, Sensor)
    readings = [driver.read() for _ in range(5)]
    assert all(r.healthy for r in readings)
    assert len({r.value for r in readings}) > 1  # varies, unlike constant mode


def test_realistic_fake_driver_is_deterministic_under_the_same_spec():
    spec = DriverSpec(
        kind="fake",
        fake_mode="realistic",
        params={"baseline": 10.0, "noise_std": 0.1, "drift_std": 0.01, "seed": 123},
    )
    d1 = build_driver("temperature", spec)
    d2 = build_driver("temperature", spec)
    assert [d1.read().value for _ in range(5)] == [d2.read().value for _ in range(5)]


def test_fake_driver_value_range_is_forwarded_to_sensor_clamp():
    spec = DriverSpec(
        kind="fake", fake_mode="constant", params={"value": 1000.0, "value_range": (0.0, 10.0)}
    )
    driver = build_driver("pressure", spec)
    assert driver.read().value == 10.0


def test_unknown_fake_mode_fails_clearly():
    with pytest.raises(UnsupportedDriverError):
        build_driver("temperature", DriverSpec(kind="fake", fake_mode="bogus", params={}))


def test_constant_fake_missing_value_param_fails_clearly():
    with pytest.raises(UnsupportedDriverError):
        build_driver("temperature", DriverSpec(kind="fake", fake_mode="constant", params={}))


def test_realistic_fake_missing_required_param_fails_clearly():
    spec = DriverSpec(kind="fake", fake_mode="realistic", params={"baseline": 1.0})
    with pytest.raises(UnsupportedDriverError):
        build_driver("temperature", spec)


# ---------------------------------------------------------------------------
# Real driver selection -- construction only, no hardware access (every real
# driver here opens its bus/sysfs lazily on read(), never in __init__)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "channel,expected_cls",
    [
        ("temperature", DS18B20Driver),
        ("vibration", ADXL335Driver),
        ("pressure", BMP280Driver),
        ("humidity", DHT22AdafruitDriver),  # registry's real humidity driver since 7f264a1
        ("current", INA219Driver),
    ],
)
def test_registry_selects_the_correct_real_driver(channel, expected_cls):
    driver = build_driver(channel, DriverSpec(kind="real"))
    assert isinstance(driver, expected_cls)
    assert isinstance(driver, SensorDriver)


def test_real_driver_construction_accepts_explicit_parameters():
    driver = build_driver(
        "pressure", DriverSpec(kind="real", params={"bus_num": 1, "address": 0x76})
    )
    assert isinstance(driver, BMP280Driver)


def test_real_driver_invalid_parameters_fail_clearly():
    with pytest.raises(UnsupportedDriverError):
        build_driver("pressure", DriverSpec(kind="real", params={"not_a_real_kwarg": 1}))


def test_unimplemented_real_driver_fails_clearly_not_silently_fake():
    """gas has no real driver (no MQ-135 implementation exists yet) --
    requesting kind="real" must fail loudly, never silently stay fake."""
    with pytest.raises(UnsupportedDriverError):
        build_driver("gas", DriverSpec(kind="real"))


def test_unknown_channel_fails_clearly():
    with pytest.raises(UnsupportedDriverError):
        build_driver("not_a_channel", DriverSpec(kind="real"))


def test_unknown_driver_kind_fails_clearly():
    with pytest.raises(UnsupportedDriverError):
        build_driver("temperature", DriverSpec(kind="bogus"))


# ---------------------------------------------------------------------------
# build_drivers() -- full channel coverage
# ---------------------------------------------------------------------------


def test_build_drivers_default_configuration_preserves_current_behavior():
    drivers = build_drivers(_default_specs())
    assert set(drivers) == set(CHANNELS)
    assert isinstance(drivers["temperature"], DS18B20Driver)
    for channel in ("vibration", "pressure", "humidity", "gas", "current"):
        assert isinstance(drivers[channel], Sensor)
    assert drivers["vibration"].read().value == 0.03
    assert drivers["pressure"].read().value == 1013.0
    assert drivers["humidity"].read().value == 45.0
    assert drivers["gas"].read().value == 150.0
    assert drivers["current"].read().value == 0.0


def test_build_drivers_missing_channel_fails_clearly():
    specs = _default_specs()
    del specs["gas"]
    with pytest.raises(ValueError):
        build_drivers(specs)


def test_build_drivers_extra_channel_fails_clearly():
    specs = _default_specs()
    specs["not_a_channel"] = DriverSpec(kind="fake", fake_mode="constant", params={"value": 0.0})
    with pytest.raises(ValueError):
        build_drivers(specs)


def test_all_fake_drivers_satisfy_the_reading_contract():
    drivers = build_drivers(_default_specs(), clock=_fixed_clock)
    for channel in ("vibration", "pressure", "humidity", "gas", "current"):
        r = drivers[channel].read()
        assert r.healthy is True
        assert isinstance(r.value, float)
        assert r.ts == "2026-01-01T00:00:00.000Z"
        assert set(r.as_dict()) == {"value", "unit", "ts", "healthy"}


# ---------------------------------------------------------------------------
# resolve_channel_specs_from_env()
# ---------------------------------------------------------------------------


def test_env_resolution_with_no_env_vars_returns_defaults_unchanged():
    defaults = _default_specs()
    assert resolve_channel_specs_from_env(defaults, env={}) == defaults


def test_env_overrides_a_single_channel_to_real():
    defaults = _default_specs()
    resolved = resolve_channel_specs_from_env(defaults, env={"SHTAPM_DRIVER_PRESSURE": "real"})
    assert resolved["pressure"] == DriverSpec(kind="real")
    for channel in ("temperature", "vibration", "humidity", "gas", "current"):
        assert resolved[channel] == defaults[channel]


def test_env_overrides_a_real_channel_back_to_fake_with_a_visible_placeholder():
    defaults = _default_specs()
    resolved = resolve_channel_specs_from_env(defaults, env={"SHTAPM_DRIVER_TEMPERATURE": "fake"})
    assert resolved["temperature"] == DriverSpec(
        kind="fake", fake_mode="constant", params={"value": 0.0}
    )


def test_env_same_kind_override_is_a_no_op():
    defaults = _default_specs()
    resolved = resolve_channel_specs_from_env(defaults, env={"SHTAPM_DRIVER_TEMPERATURE": "real"})
    assert resolved == defaults


def test_env_invalid_driver_kind_fails_clearly():
    defaults = _default_specs()
    with pytest.raises(UnsupportedDriverError):
        resolve_channel_specs_from_env(defaults, env={"SHTAPM_DRIVER_PRESSURE": "bogus"})


def test_env_fake_signal_mode_switches_fake_channels_to_realistic():
    defaults = _default_specs()
    resolved = resolve_channel_specs_from_env(
        defaults, env={"SHTAPM_FAKE_SIGNAL_MODE": "realistic"}
    )
    assert resolved["temperature"].kind == "real"  # real channels untouched by signal mode
    for channel in ("vibration", "pressure", "humidity", "gas", "current"):
        assert resolved[channel].kind == "fake"
        assert resolved[channel].fake_mode == "realistic"
        assert "baseline" in resolved[channel].params


def test_env_fake_signal_mode_realistic_then_back_to_constant_round_trips():
    defaults = _default_specs()
    realistic = resolve_channel_specs_from_env(
        defaults, env={"SHTAPM_FAKE_SIGNAL_MODE": "realistic"}
    )
    back = resolve_channel_specs_from_env(realistic, env={"SHTAPM_FAKE_SIGNAL_MODE": "constant"})
    for channel in ("vibration", "pressure", "humidity", "gas", "current"):
        assert back[channel].fake_mode == "constant"


def test_env_invalid_fake_signal_mode_fails_clearly():
    defaults = _default_specs()
    with pytest.raises(UnsupportedDriverError):
        resolve_channel_specs_from_env(defaults, env={"SHTAPM_FAKE_SIGNAL_MODE": "bogus"})


def test_env_resolution_can_feed_directly_into_build_drivers():
    defaults = _default_specs()
    resolved = resolve_channel_specs_from_env(
        defaults,
        env={"SHTAPM_DRIVER_TEMPERATURE": "fake", "SHTAPM_FAKE_SIGNAL_MODE": "realistic"},
    )
    drivers = build_drivers(resolved)
    assert isinstance(drivers["temperature"], Sensor)
    assert set(drivers) == set(CHANNELS)


def test_env_resolution_defaults_missing_channel_fails_clearly():
    defaults = _default_specs()
    del defaults["gas"]
    with pytest.raises(ValueError):
        resolve_channel_specs_from_env(defaults, env={})


def test_env_resolution_reads_os_environ_by_default(monkeypatch):
    defaults = _default_specs()
    monkeypatch.setenv("SHTAPM_DRIVER_PRESSURE", "real")
    resolved = resolve_channel_specs_from_env(defaults)
    assert resolved["pressure"].kind == "real"
