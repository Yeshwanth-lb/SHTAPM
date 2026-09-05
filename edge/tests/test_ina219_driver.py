"""Real INA219 driver tests (P1 · C1) — hardware-free with mocks.

Tests the INA219Driver and ina219_raw_read with proper calibration configuration.
Mocks smbus2.SMBus to inject I²C register values and failure modes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import edge.drivers.ina219 as ina219_module
from edge.drivers.ina219 import INA219CurrentReader, INA219Driver, ina219_raw_read


class TestINA219Calibration:
    """Test calibration constant calculation."""

    def test_calibration_constant_typical_5a_0p1ohm(self):
        """Typical case: 5A max, 0.1Ω shunt."""
        reader = INA219CurrentReader(max_expected_amps=5.0, shunt_ohms=0.1)
        # Current_LSB = 5.0 / 32767 ≈ 0.0001526 A/LSB
        # Calibration = 0.04096 / (0.0001526 × 0.1) ≈ 2686
        assert 2680 <= reader._calibration <= 2690
        assert abs(reader._current_lsb - 0.0001526) < 0.00001

    def test_calibration_constant_2a_0p05ohm(self):
        """Alternative case: 2A max, 0.05Ω shunt."""
        reader = INA219CurrentReader(max_expected_amps=2.0, shunt_ohms=0.05)
        # Current_LSB = 2.0 / 32767 ≈ 0.0000610 A/LSB
        # Calibration = 0.04096 / (0.0000610 × 0.05) ≈ 13421
        assert 13410 <= reader._calibration <= 13430

    def test_calibration_constant_10a_0p1ohm(self):
        """High current: 10A max, 0.1Ω shunt."""
        reader = INA219CurrentReader(max_expected_amps=10.0, shunt_ohms=0.1)
        # Current_LSB = 10.0 / 32767 ≈ 0.0003052 A/LSB
        # Calibration = 0.04096 / (0.0003052 × 0.1) ≈ 1343
        assert 1340 <= reader._calibration <= 1346


class TestINA219CurrentReader:
    """Test the low-level I²C reader with calibration."""

    def test_read_current_amps_healthy_zero(self):
        """Read zero current from register (INA219 idle)."""
        mock_bus = MagicMock()
        # Calibration write succeeds
        mock_bus.write_i2c_block_data.return_value = None
        # Current register (0x04) returns 0x0000 (0 counts)
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x00]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(
                bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
            )
            amps = reader.read_current_amps()

            assert amps == 0.0
            mock_bus.close.assert_called_once()
            # Verify calibration was written to register 0x05
            mock_bus.write_i2c_block_data.assert_called_once()
            call_args = mock_bus.write_i2c_block_data.call_args
            assert call_args[0][0] == 0x40  # address
            assert call_args[0][1] == 0x05  # register 0x05 (calibration)
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_positive(self):
        """Read positive current (e.g. 0.5 A)."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        # For 5A max / 0.1Ω shunt: Current_LSB ≈ 0.0001526 A
        # 0.5A ÷ 0.0001526 ≈ 3276 counts = 0x0CCC
        mock_bus.read_i2c_block_data.return_value = [0x0C, 0xCC]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(
                bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
            )
            amps = reader.read_current_amps()

            assert abs(amps - 0.5) < 0.001
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_negative(self):
        """Read negative current (discharging/reverse flow)."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        # -0.5A = -3276 counts = 0xF334 (two's complement)
        mock_bus.read_i2c_block_data.return_value = [0xF3, 0x34]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(
                bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
            )
            amps = reader.read_current_amps()

            assert abs(amps - (-0.5)) < 0.001
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_custom_calibration(self):
        """Custom max_expected_amps and shunt_ohms are respected."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        # 1A max, 0.1Ω: Current_LSB = 1.0/32767 ≈ 0.0000305 A
        # For 0.1A: 0.1 / 0.0000305 ≈ 3277 counts = 0x0CCD
        mock_bus.read_i2c_block_data.return_value = [0x0C, 0xCD]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(
                bus_num=1, address=0x40, max_expected_amps=1.0, shunt_ohms=0.1
            )
            amps = reader.read_current_amps()

            # Should be close to 0.1A with different LSB
            assert abs(amps - 0.1) < 0.001
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_calibration_only_written_once(self):
        """Calibration register is written only on first read, then cached."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x00]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(
                bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
            )

            # First read
            reader.read_current_amps()
            first_write_call_count = mock_bus.write_i2c_block_data.call_count

            # Second read
            reader.read_current_amps()
            second_write_call_count = mock_bus.write_i2c_block_data.call_count

            # Calibration should only be written once
            assert first_write_call_count == 1
            assert second_write_call_count == 1
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_calibration_write_failure(self):
        """Calibration write failure raises OSError."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.side_effect = OSError("I2C write failed")
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(bus_num=1, address=0x40)
            with pytest.raises(OSError, match="failed to calibrate"):
                reader.read_current_amps()
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_register_read_failure(self):
        """I²C register read fails (device not responding)."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        mock_bus.read_i2c_block_data.side_effect = OSError("I2CError: NAK on register 0x04")
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(bus_num=1, address=0x40)
            with pytest.raises(OSError, match="I2CError"):
                reader.read_current_amps()
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_bus_open_failure(self):
        """I²C bus open fails (no /dev/i2c-1 or permission denied)."""
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.side_effect = OSError("Permission denied")

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(bus_num=1, address=0x40)
            with pytest.raises(OSError, match="failed to open I²C bus"):
                reader.read_current_amps()
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_smbus2_not_installed(self):
        """smbus2 not installed raises ImportError with hint."""
        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = None
            reader = INA219CurrentReader(bus_num=1, address=0x40)
            with pytest.raises(ImportError, match="pip install smbus2"):
                reader.read_current_amps()
        finally:
            ina219_module.smbus2 = original_smbus2


class TestINA219RawRead:
    """Test the ina219_raw_read factory."""

    def test_ina219_raw_read_returns_callable(self):
        """ina219_raw_read returns a RawRead callable."""
        raw_read = ina219_raw_read(bus_num=1, address=0x40)
        assert callable(raw_read)

    def test_ina219_raw_read_invokes_reader(self):
        """Calling the raw_read invokes the underlying reader."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x64]  # 100 counts
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            raw_read = ina219_raw_read(bus_num=1, address=0x40, max_expected_amps=5.0)
            amps = raw_read()

            assert amps > 0  # Some positive current
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_ina219_raw_read_failure_raises(self):
        """Raw read raises on I²C failure (caller must wrap in Sensor)."""
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value.write_i2c_block_data.side_effect = OSError("NAK")

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            raw_read = ina219_raw_read()
            with pytest.raises(OSError):
                raw_read()
        finally:
            ina219_module.smbus2 = original_smbus2


class TestINA219Driver:
    """Test the full SensorDriver implementation."""

    def test_driver_read_healthy(self):
        """Driver read returns a healthy Reading."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        mock_bus.read_i2c_block_data.return_value = [0x0C, 0xCC]  # ~0.5A
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver(bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1)
            reading = driver.read()

            assert reading.healthy is True
            assert abs(reading.value - 0.5) < 0.01
            assert reading.unit == "A"
            assert reading.ts is not None
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_read_i2c_failure_returns_unhealthy(self):
        """Driver read returns unhealthy Reading on I²C failure (never raises)."""
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value.write_i2c_block_data.side_effect = OSError("NAK")

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver(bus_num=1, address=0x40)
            reading = driver.read()

            assert reading.healthy is False
            assert reading.value is None
            assert reading.unit == "A"
            assert reading.ts is not None
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_read_bus_open_failure_returns_unhealthy(self):
        """Driver read returns unhealthy if bus cannot open (never raises)."""
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.side_effect = PermissionError("permission denied")

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver(bus_num=1, address=0x40)
            reading = driver.read()

            assert reading.healthy is False
            assert reading.value is None
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_read_recovers_after_failure(self):
        """Driver read recovers after a transient failure (resilient)."""
        mock_bus_fail = MagicMock()
        mock_bus_fail.write_i2c_block_data.side_effect = OSError("NAK")

        mock_bus_success = MagicMock()
        mock_bus_success.write_i2c_block_data.return_value = None
        mock_bus_success.read_i2c_block_data.return_value = [0x00, 0x32]  # ~0.05A

        mock_smbus2_fail = MagicMock()
        mock_smbus2_fail.SMBus.return_value = mock_bus_fail

        mock_smbus2_success = MagicMock()
        mock_smbus2_success.SMBus.return_value = mock_bus_success

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2_fail
            driver = INA219Driver(bus_num=1, address=0x40)

            # First read fails
            reading1 = driver.read()
            assert reading1.healthy is False

            # Switch to success mock and second read succeeds
            ina219_module.smbus2 = mock_smbus2_success
            reading2 = driver.read()
            assert reading2.healthy is True
            assert reading2.value > 0
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_implements_sensor_driver(self):
        """INA219Driver is a SensorDriver."""
        from edge.drivers.base import SensorDriver

        driver = INA219Driver()
        assert isinstance(driver, SensorDriver)

    def test_driver_read_negative_current(self):
        """Driver correctly handles negative current (reverse flow)."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        mock_bus.read_i2c_block_data.return_value = [0xF3, 0x34]  # ~-0.5A
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver(bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1)
            reading = driver.read()

            assert reading.healthy is True
            assert reading.value < 0
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_reading_shape(self):
        """Driver read returns complete Reading with all fields."""
        mock_bus = MagicMock()
        mock_bus.write_i2c_block_data.return_value = None
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x64]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver()
            reading = driver.read()

            assert hasattr(reading, "value")
            assert hasattr(reading, "unit")
            assert hasattr(reading, "ts")
            assert hasattr(reading, "healthy")
            assert isinstance(reading.as_dict(), dict)
            assert set(reading.as_dict().keys()) == {"value", "unit", "ts", "healthy"}
        finally:
            ina219_module.smbus2 = original_smbus2
