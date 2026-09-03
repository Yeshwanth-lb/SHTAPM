"""Real ADXL335 driver tests (P1 · C1) — hardware-free with mocked spidev.

Tests ADXL335MCP3008Reader (raw X/Y/Z ADC reads), ADXL335VibrationReader
(baseline + magnitude combination), adxl335_raw_read, and ADXL335Driver.
Mocks spidev.SpiDev to inject MCP3008 SPI replies and failure modes,
following the same module-level-mock pattern as edge/tests/test_ina219_driver.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import edge.drivers.adxl335 as adxl335_module
from edge.drivers.adxl335 import (
    ADXL335Driver,
    ADXL335MCP3008Reader,
    ADXL335VibrationReader,
    adxl335_raw_read,
)

# Independently-derived ground truth (not imported from the module under test).
_VOLTS_PER_COUNT = 3.3 / 1024
_G_PER_COUNT = _VOLTS_PER_COUNT / 0.330


def _reply_for(value: int) -> list[int]:
    """Build a realistic 3-byte MCP3008 SPI reply for a given 10-bit ADC value."""
    return [0, (value >> 8) & 0x03, value & 0xFF]


def _mock_spi_for_channels(channel_values: dict[int, int]) -> MagicMock:
    """Mock SpiDev whose xfer2() replies per-channel based on the command bytes."""
    mock_spi = MagicMock()

    def _xfer2(cmd):
        channel = (cmd[1] >> 4) - 8
        return _reply_for(channel_values[channel])

    mock_spi.xfer2.side_effect = _xfer2
    return mock_spi


class TestADXL335MCP3008Reader:
    """Test the low-level MCP3008 SPI reader."""

    def test_read_raw_xyz_typical(self):
        mock_spi = _mock_spi_for_channels({0: 200, 1: 10, 2: 5})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335MCP3008Reader(bus=0, device=0, x_channel=0, y_channel=1, z_channel=2)
            x, y, z = reader.read_raw_xyz()

            assert (x, y, z) == (200, 10, 5)
            mock_spi.open.assert_called_once_with(0, 0)
            mock_spi.close.assert_called_once()
        finally:
            adxl335_module.spidev = original_spidev

    def test_read_raw_xyz_max_value(self):
        mock_spi = _mock_spi_for_channels({0: 1023, 1: 1023, 2: 1023})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335MCP3008Reader()
            assert reader.read_raw_xyz() == (1023, 1023, 1023)
        finally:
            adxl335_module.spidev = original_spidev

    def test_read_raw_xyz_zero_value(self):
        mock_spi = _mock_spi_for_channels({0: 0, 1: 0, 2: 0})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335MCP3008Reader()
            assert reader.read_raw_xyz() == (0, 0, 0)
        finally:
            adxl335_module.spidev = original_spidev

    def test_custom_channel_mapping(self):
        """Channels can be remapped (e.g. if wired differently)."""
        mock_spi = _mock_spi_for_channels({3: 111, 4: 222, 5: 333})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335MCP3008Reader(x_channel=3, y_channel=4, z_channel=5)
            assert reader.read_raw_xyz() == (111, 222, 333)
        finally:
            adxl335_module.spidev = original_spidev

    def test_out_of_range_channel_raises_value_error(self):
        with pytest.raises(ValueError, match="x_channel"):
            ADXL335MCP3008Reader(x_channel=8)
        with pytest.raises(ValueError, match="y_channel"):
            ADXL335MCP3008Reader(y_channel=-1)
        with pytest.raises(ValueError, match="z_channel"):
            ADXL335MCP3008Reader(z_channel=99)

    def test_spi_open_failure_raises_oserror(self):
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value.open.side_effect = OSError("No such device")

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335MCP3008Reader()
            with pytest.raises(OSError, match="failed to open SPI bus"):
                reader.read_raw_xyz()
        finally:
            adxl335_module.spidev = original_spidev

    def test_spi_transfer_failure_raises_oserror(self):
        """A non-OSError transfer failure (e.g. a spidev-internal exception) is
        wrapped into OSError with context."""
        mock_spi = MagicMock()
        mock_spi.xfer2.side_effect = RuntimeError("SPI transfer error")
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335MCP3008Reader()
            with pytest.raises(OSError, match="SPI read failed"):
                reader.read_raw_xyz()
            mock_spi.close.assert_called_once()  # cleaned up despite failure
        finally:
            adxl335_module.spidev = original_spidev

    def test_spi_transfer_oserror_propagates_unwrapped(self):
        """An OSError raised directly by the SPI transfer (e.g. a real I/O
        error) is not double-wrapped — its original message is preserved."""
        mock_spi = MagicMock()
        mock_spi.xfer2.side_effect = OSError("SPI transfer error")
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335MCP3008Reader()
            with pytest.raises(OSError, match="SPI transfer error"):
                reader.read_raw_xyz()
            mock_spi.close.assert_called_once()  # cleaned up despite failure
        finally:
            adxl335_module.spidev = original_spidev

    def test_out_of_range_adc_value_raises_oserror(self):
        """Malformed/corrupted reply (e.g. a misbehaving mock or driver bug)
        outside the physically possible 0-1023 range is treated as invalid."""
        mock_spi = MagicMock()
        mock_spi.xfer2.return_value = [0, 0, 2000]  # out of 10-bit range
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335MCP3008Reader()
            with pytest.raises(OSError, match="invalid MCP3008 reading"):
                reader.read_raw_xyz()
        finally:
            adxl335_module.spidev = original_spidev

    def test_spidev_not_installed_raises_import_error(self):
        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = None
            reader = ADXL335MCP3008Reader()
            with pytest.raises(ImportError, match="pip install spidev"):
                reader.read_raw_xyz()
        finally:
            adxl335_module.spidev = original_spidev


class TestADXL335VibrationReader:
    """Test the baseline + magnitude combination into a single g scalar."""

    def test_first_read_establishes_baseline_and_returns_zero(self):
        mock_spi = _mock_spi_for_channels({0: 500, 1: 480, 2: 510})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335VibrationReader()
            assert reader.read_vibration_g() == 0.0
            assert reader._baseline == (500, 480, 510)
        finally:
            adxl335_module.spidev = original_spidev

    def test_subsequent_read_reports_deviation_magnitude_in_g(self):
        mock_spidev = MagicMock()
        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335VibrationReader()

            mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 500, 1: 500, 2: 500})
            first = reader.read_vibration_g()
            assert first == 0.0

            # X moves by +100 counts, Y/Z unchanged (matches the user's
            # unsoldered-breadboard scenario: only X actually varies)
            mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 600, 1: 500, 2: 500})
            second = reader.read_vibration_g()
            expected = 100 * _G_PER_COUNT
            assert second == pytest.approx(expected)
        finally:
            adxl335_module.spidev = original_spidev

    def test_three_axis_deviation_combines_as_euclidean_magnitude(self):
        mock_spidev = MagicMock()
        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335VibrationReader()

            mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 500, 1: 500, 2: 500})
            reader.read_vibration_g()

            # dx=3, dy=4, dz=0 -> magnitude 5 counts (3-4-5 triangle, easy to verify)
            mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 503, 1: 504, 2: 500})
            g = reader.read_vibration_g()
            assert g == pytest.approx(5 * _G_PER_COUNT)
        finally:
            adxl335_module.spidev = original_spidev

    def test_unsoldered_axis_baseline_absorbs_constant_offset(self):
        """An axis that's wired but stuck at a constant (physically arbitrary)
        value — like the user's unsoldered Y/Z — contributes ~0 regardless of
        its absolute baseline value, once that value stops changing."""
        mock_spidev = MagicMock()
        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335VibrationReader()

            # Y/Z stuck near 0 (floating), X at a plausible moving baseline
            mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 150, 1: 8, 2: 8})
            reader.read_vibration_g()

            # Y/Z stay exactly the same; only X moves
            mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 200, 1: 8, 2: 8})
            g = reader.read_vibration_g()
            assert g == pytest.approx(50 * _G_PER_COUNT)
        finally:
            adxl335_module.spidev = original_spidev

    def test_read_failure_raises(self):
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value.open.side_effect = OSError("no device")

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            reader = ADXL335VibrationReader()
            with pytest.raises(OSError):
                reader.read_vibration_g()
        finally:
            adxl335_module.spidev = original_spidev


class TestADXL335RawRead:
    """Test the adxl335_raw_read factory."""

    def test_returns_callable(self):
        mock_spi = _mock_spi_for_channels({0: 100, 1: 100, 2: 100})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            raw_read = adxl335_raw_read()
            assert callable(raw_read)
        finally:
            adxl335_module.spidev = original_spidev

    def test_invokes_reader(self):
        mock_spi = _mock_spi_for_channels({0: 100, 1: 100, 2: 100})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            raw_read = adxl335_raw_read()
            assert raw_read() == 0.0  # first call establishes baseline
        finally:
            adxl335_module.spidev = original_spidev

    def test_failure_raises(self):
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value.open.side_effect = OSError("nope")

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            raw_read = adxl335_raw_read()
            with pytest.raises(OSError):
                raw_read()
        finally:
            adxl335_module.spidev = original_spidev


class TestADXL335Driver:
    """Test the full SensorDriver implementation."""

    def test_driver_read_healthy_first_sample_is_zero_baseline(self):
        mock_spi = _mock_spi_for_channels({0: 500, 1: 500, 2: 500})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            driver = ADXL335Driver()
            reading = driver.read()

            assert reading.healthy is True
            assert reading.value == 0.0
            assert reading.unit == "g"
            assert reading.ts is not None
        finally:
            adxl335_module.spidev = original_spidev

    def test_driver_read_spi_failure_returns_unhealthy(self):
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value.open.side_effect = OSError("no device")

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            driver = ADXL335Driver()
            reading = driver.read()

            assert reading.healthy is False
            assert reading.value is None
            assert reading.unit == "g"
            assert reading.ts is not None
        finally:
            adxl335_module.spidev = original_spidev

    def test_driver_read_recovers_after_failure(self):
        """Driver read recovers after a transient failure (resilient)."""
        mock_spidev_fail = MagicMock()
        mock_spidev_fail.SpiDev.return_value.open.side_effect = OSError("transient")

        mock_spidev_ok = MagicMock()
        mock_spidev_ok.SpiDev.return_value = _mock_spi_for_channels({0: 500, 1: 500, 2: 500})

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev_fail
            driver = ADXL335Driver()

            reading1 = driver.read()
            assert reading1.healthy is False

            adxl335_module.spidev = mock_spidev_ok
            reading2 = driver.read()
            assert reading2.healthy is True
            assert reading2.value == 0.0  # first successful read establishes baseline
        finally:
            adxl335_module.spidev = original_spidev

    def test_driver_implements_sensor_driver(self):
        from edge.drivers.base import SensorDriver

        driver = ADXL335Driver()
        assert isinstance(driver, SensorDriver)

    def test_driver_reading_shape(self):
        mock_spi = _mock_spi_for_channels({0: 100, 1: 100, 2: 100})
        mock_spidev = MagicMock()
        mock_spidev.SpiDev.return_value = mock_spi

        original_spidev = adxl335_module.spidev
        try:
            adxl335_module.spidev = mock_spidev
            driver = ADXL335Driver()
            reading = driver.read()

            assert hasattr(reading, "value")
            assert hasattr(reading, "unit")
            assert hasattr(reading, "ts")
            assert hasattr(reading, "healthy")
            assert isinstance(reading.as_dict(), dict)
            assert set(reading.as_dict().keys()) == {"value", "unit", "ts", "healthy"}
        finally:
            adxl335_module.spidev = original_spidev
