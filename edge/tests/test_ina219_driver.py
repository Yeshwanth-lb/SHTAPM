"""Real INA219 driver tests (P1 · C1) — hardware-free with mocks.

Tests the INA219Driver and ina219_raw_read without physical hardware.
Mocks smbus2.SMBus to inject I²C register values and failure modes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import edge.drivers.ina219 as ina219_module
from edge.drivers.ina219 import INA219CurrentReader, INA219Driver, ina219_raw_read


class TestINA219CurrentReader:
    """Test the low-level I²C reader."""

    def test_read_current_amps_healthy_zero(self):
        """Read zero current from register (INA219 idle)."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x00]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(bus_num=1, address=0x40, current_lsb_ma=10.0)
            amps = reader.read_current_amps()

            assert amps == 0.0
            mock_bus.close.assert_called_once()
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_positive(self):
        """Read positive current (e.g. 0.5 A = 50 mA)."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x32]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(bus_num=1, address=0x40, current_lsb_ma=10.0)
            amps = reader.read_current_amps()

            assert amps == 0.5
            mock_smbus2.SMBus.assert_called_with(1)
            mock_bus.read_i2c_block_data.assert_called_with(0x40, 0x07, 2)
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_negative(self):
        """Read negative current (discharging/reverse flow)."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.return_value = [0xFF, 0x9C]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(bus_num=1, address=0x40, current_lsb_ma=10.0)
            amps = reader.read_current_amps()

            assert amps == -1.0
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_read_current_amps_custom_lsb(self):
        """Respect custom CURRENT_LSB (e.g. 1 mA/LSB for finer resolution)."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x2A]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(bus_num=1, address=0x40, current_lsb_ma=1.0)
            amps = reader.read_current_amps()

            assert amps == 0.042
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

    def test_read_current_amps_register_read_failure(self):
        """I²C register read fails (device not responding, NAK)."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.side_effect = OSError("I2CError: NAK on register 0x07")
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

    def test_read_current_amps_custom_bus_and_address(self):
        """Respect custom bus number and I²C address."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x64]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            reader = INA219CurrentReader(bus_num=3, address=0x41)
            amps = reader.read_current_amps()

            mock_smbus2.SMBus.assert_called_with(3)
            mock_bus.read_i2c_block_data.assert_called_with(0x41, 0x07, 2)
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
        raw_read = ina219_raw_read(bus_num=1, address=0x40, current_lsb_ma=10.0)
        assert callable(raw_read)

    def test_ina219_raw_read_invokes_reader(self):
        """Calling the raw_read invokes the underlying reader."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x64]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            raw_read = ina219_raw_read(bus_num=1, address=0x40, current_lsb_ma=10.0)
            amps = raw_read()

            assert amps == 1.0
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_ina219_raw_read_failure_raises(self):
        """Raw read raises on I²C failure (caller must wrap in Sensor)."""
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.side_effect = OSError("NAK")

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
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x64]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver(bus_num=1, address=0x40, current_lsb_ma=10.0)
            reading = driver.read()

            assert reading.healthy is True
            assert reading.value == 1.0
            assert reading.unit == "A"
            assert reading.ts is not None
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_read_i2c_failure_returns_unhealthy(self):
        """Driver read returns unhealthy Reading on I²C failure (never raises)."""
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.side_effect = OSError("NAK")

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
        # First call fails
        mock_smbus2_fail = MagicMock()
        mock_smbus2_fail.SMBus.side_effect = OSError("NAK")

        # Second call succeeds
        mock_bus_success = MagicMock()
        mock_bus_success.read_i2c_block_data.return_value = [0x00, 0x32]
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
            assert reading2.value == 0.5
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
        mock_bus.read_i2c_block_data.return_value = [0xFF, 0x9C]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver(bus_num=1, address=0x40, current_lsb_ma=10.0)
            reading = driver.read()

            assert reading.healthy is True
            assert reading.value == -1.0
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_read_large_current(self):
        """Driver handles large current values (e.g. 3.27 A)."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.return_value = [0x01, 0x47]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver(bus_num=1, address=0x40, current_lsb_ma=10.0)
            reading = driver.read()

            assert reading.healthy is True
            assert abs(reading.value - 3.27) < 0.001
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_custom_lsb_propagates(self):
        """Custom current_lsb_ma is correctly applied."""
        mock_bus = MagicMock()
        mock_bus.read_i2c_block_data.return_value = [0x00, 0x2A]
        mock_smbus2 = MagicMock()
        mock_smbus2.SMBus.return_value = mock_bus

        original_smbus2 = ina219_module.smbus2
        try:
            ina219_module.smbus2 = mock_smbus2
            driver = INA219Driver(bus_num=1, address=0x40, current_lsb_ma=1.0)
            reading = driver.read()

            assert reading.healthy is True
            assert abs(reading.value - 0.042) < 0.0001
        finally:
            ina219_module.smbus2 = original_smbus2

    def test_driver_reading_shape(self):
        """Driver read returns complete Reading with all fields."""
        mock_bus = MagicMock()
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
