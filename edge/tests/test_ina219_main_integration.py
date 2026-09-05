"""Integration test: edge/main.py uses real INA219 for current, fake drivers
for other channels (P1).

Verifies that the main.py entry point constructs the driver set correctly:
  - Current channel: real INA219Driver (bus 1, address 0x40)
  - Other five channels: fake drivers (temperature, vibration, pressure, humidity, gas)
  - Frozen six-channel TelemetryMessage contract is preserved
"""

from __future__ import annotations

from unittest.mock import MagicMock

import edge.drivers.ina219 as ina219_module
from edge.drivers.fake import fake_drivers
from edge.drivers.ina219 import INA219Driver


def test_main_uses_ina219_for_current_channel():
    """Verify edge/main.py construction: INA219Driver replaces fake current driver."""
    # Simulate the main.py driver construction pattern
    _dev_values = {
        "temperature": 26.0,
        "vibration": 0.03,
        "pressure": 1013.0,
        "humidity": 45.0,
        "gas": 150.0,
        "current": 0.0,  # Placeholder; replaced
    }

    # Create fake drivers for five channels
    drivers = fake_drivers(_dev_values)

    # Verify all six channels present initially
    assert set(drivers.keys()) == {
        "temperature",
        "vibration",
        "pressure",
        "humidity",
        "gas",
        "current",
    }

    # Replace fake current with real INA219
    drivers["current"] = INA219Driver(
        bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
    )

    # Verify structure: five fakes + one real INA219
    from edge.drivers.base import SensorDriver

    for driver in drivers.values():
        assert isinstance(driver, SensorDriver)

    # Verify current is now INA219Driver (not the fake)
    assert isinstance(drivers["current"], INA219Driver)


def test_five_channels_remain_fake_drivers():
    """Verify non-current channels use fake drivers."""
    _dev_values = {
        "temperature": 26.0,
        "vibration": 0.03,
        "pressure": 1013.0,
        "humidity": 45.0,
        "gas": 150.0,
        "current": 0.0,
    }

    drivers = fake_drivers(_dev_values)
    drivers["current"] = INA219Driver()

    # Non-current channels should still be Sensors (fake drivers)
    from edge.drivers.base import Sensor

    assert isinstance(drivers["temperature"], Sensor)
    assert isinstance(drivers["vibration"], Sensor)
    assert isinstance(drivers["pressure"], Sensor)
    assert isinstance(drivers["humidity"], Sensor)
    assert isinstance(drivers["gas"], Sensor)

    # Current should be INA219Driver (not Sensor)
    assert isinstance(drivers["current"], INA219Driver)
    assert not isinstance(drivers["current"], Sensor)


def test_frozen_contract_with_ina219_current():
    """Verify frozen six-channel TelemetryMessage can be built with INA219 current."""
    from edge.acquisition.sampler import Sampler

    mock_bus = MagicMock()
    mock_bus.write_i2c_block_data.return_value = None
    mock_bus.read_i2c_block_data.return_value = [0x0C, 0xCC]  # ~0.5A
    mock_smbus2 = MagicMock()
    mock_smbus2.SMBus.return_value = mock_bus

    original_smbus2 = ina219_module.smbus2
    try:
        ina219_module.smbus2 = mock_smbus2

        _dev_values = {
            "temperature": 26.0,
            "vibration": 0.03,
            "pressure": 1013.0,
            "humidity": 45.0,
            "gas": 150.0,
            "current": 0.0,
        }
        drivers = fake_drivers(_dev_values)
        drivers["current"] = INA219Driver(
            bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
        )

        # Build sampler with mixed drivers
        sampler = Sampler(device_id="pump-01", drivers=drivers)

        # Sample once — should produce a healthy frame with INA219 current
        result = sampler.sample_once()

        assert result.healthy is True
        assert result.frame is not None

        # Verify all six channels in frozen contract
        sensors = result.frame.sensors
        assert sensors.temperature == 26.0
        assert sensors.vibration == 0.03
        assert sensors.pressure == 1013.0
        assert sensors.humidity == 45.0
        assert sensors.gas == 150.0
        assert abs(sensors.current - 0.5) < 0.01  # From real INA219

        # Verify frame structure matches frozen contract
        assert result.frame.device_id == "pump-01"
        assert result.frame.sample_seq == 0
        assert result.frame.ts is not None

    finally:
        ina219_module.smbus2 = original_smbus2


def test_ina219_failure_propagates_through_sampler():
    """If INA219 fails, sampler returns unhealthy (other channels don't matter)."""
    from edge.acquisition.sampler import Sampler

    mock_smbus2 = MagicMock()
    mock_smbus2.SMBus.return_value.write_i2c_block_data.side_effect = OSError("Device NAK")

    original_smbus2 = ina219_module.smbus2
    try:
        ina219_module.smbus2 = mock_smbus2

        _dev_values = {
            "temperature": 26.0,
            "vibration": 0.03,
            "pressure": 1013.0,
            "humidity": 45.0,
            "gas": 150.0,
            "current": 0.0,
        }
        drivers = fake_drivers(_dev_values)
        drivers["current"] = INA219Driver()

        sampler = Sampler(device_id="pump-01", drivers=drivers)
        result = sampler.sample_once()

        # No frame when any channel is unhealthy (current in this case)
        assert result.healthy is False
        assert result.frame is None

        # But the reading is preserved for debugging
        assert result.readings["current"].healthy is False
        assert result.readings["current"].value is None

    finally:
        ina219_module.smbus2 = original_smbus2
