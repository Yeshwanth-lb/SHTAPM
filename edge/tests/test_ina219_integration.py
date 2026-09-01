"""INA219 hardware driver integration with Sampler and AcquisitionRuntime (P1 · C1→C2 integration).

Demonstrates the INA219Driver's integration with the real C2 Sampler,
assembling a frozen TelemetryMessage and feeding it to the AcquisitionRuntime.
No physical hardware; mocks inject I²C register values.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import edge.drivers.ina219 as ina219_module
from edge.acquisition.sampler import Sampler
from edge.drivers.fake import fake_drivers
from edge.drivers.ina219 import INA219Driver


def test_ina219_driver_integrates_with_sampler():
    """INA219Driver can be used in place of fake_drivers for the current channel.

    This test demonstrates the architectural pattern for swapping in the real
    INA219 driver for the fake one when hardware is available.
    """
    # Set up mock I²C bus for INA219
    mock_bus = MagicMock()
    mock_bus.write_i2c_block_data.return_value = None
    # 0x0CCC = 3276 counts; with 5A max / 0.1Ω: ~0.5 A
    mock_bus.read_i2c_block_data.return_value = [0x0C, 0xCC]
    mock_smbus2 = MagicMock()
    mock_smbus2.SMBus.return_value = mock_bus

    original_smbus2 = ina219_module.smbus2
    try:
        ina219_module.smbus2 = mock_smbus2

        # Create fake drivers for all six channels (current will be replaced)
        fake_values = {
            "temperature": 26.0,
            "vibration": 0.03,
            "pressure": 1013.0,
            "humidity": 45.0,
            "gas": 150.0,
            "current": 0.0,  # placeholder; will be replaced
        }
        drivers = fake_drivers(fake_values)

        # Replace the fake current driver with the real INA219 driver
        # (with typical calibration: 5A max, 0.1Ω shunt)
        drivers["current"] = INA219Driver(
            bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
        )

        # Create sampler with mixed real + fake drivers
        sampler = Sampler(device_id="pump-01", drivers=drivers)

        # Sample once — should produce a healthy frame
        result = sampler.sample_once()

        # Verify frame was built
        assert result.healthy is True
        assert result.frame is not None
        assert result.frame.device_id == "pump-01"
        assert result.frame.sample_seq == 0

        # Verify all six channels present in frozen contract
        sensors = result.frame.sensors
        assert sensors.temperature == 26.0
        assert sensors.vibration == 0.03
        assert sensors.pressure == 1013.0
        assert sensors.humidity == 45.0
        assert sensors.gas == 150.0
        assert abs(sensors.current - 0.5) < 0.01  # From real INA219 driver (~0.5 A)

    finally:
        ina219_module.smbus2 = original_smbus2


def test_ina219_driver_unhealthy_read_propagates_through_sampler():
    """If INA219 read fails, sampler returns no frame (unhealthy tick).

    This demonstrates the architecture's handling of hardware failures:
    no frame is produced, and the C3 publisher does not emit anything.
    """
    # Mock I²C bus to fail during calibration write
    mock_smbus2 = MagicMock()
    mock_smbus2.SMBus.return_value.write_i2c_block_data.side_effect = OSError("Device not responding")

    original_smbus2 = ina219_module.smbus2
    try:
        ina219_module.smbus2 = mock_smbus2

        fake_values = {
            "temperature": 26.0,
            "vibration": 0.03,
            "pressure": 1013.0,
            "humidity": 45.0,
            "gas": 150.0,
            "current": 0.0,  # placeholder; will be replaced
        }
        drivers = fake_drivers(fake_values)
        drivers["current"] = INA219Driver(
            bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
        )

        sampler = Sampler(device_id="pump-01", drivers=drivers)
        result = sampler.sample_once()

        # Because INA219 read is unhealthy, no frame is built
        assert result.healthy is False
        assert result.frame is None

        # But the individual readings are preserved (for debugging)
        assert "current" in result.readings
        assert result.readings["current"].healthy is False
        assert result.readings["current"].value is None

    finally:
        ina219_module.smbus2 = original_smbus2
