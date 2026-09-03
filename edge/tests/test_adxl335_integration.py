"""ADXL335 hardware driver integration with Sampler and AcquisitionRuntime (P1 · C1→C2).

Demonstrates the ADXL335Driver's integration with the real C2 Sampler,
assembling a frozen TelemetryMessage. No physical hardware; a mocked
spidev.SpiDev stands in for the MCP3008.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import edge.drivers.adxl335 as adxl335_module
from edge.acquisition.sampler import Sampler
from edge.drivers.adxl335 import ADXL335Driver
from edge.drivers.fake import fake_drivers

_VOLTS_PER_COUNT = 3.3 / 1024
_G_PER_COUNT = _VOLTS_PER_COUNT / 0.330


def _reply_for(value: int) -> list[int]:
    return [0, (value >> 8) & 0x03, value & 0xFF]


def _mock_spi_for_channels(channel_values: dict[int, int]) -> MagicMock:
    mock_spi = MagicMock()

    def _xfer2(cmd):
        channel = (cmd[1] >> 4) - 8
        return _reply_for(channel_values[channel])

    mock_spi.xfer2.side_effect = _xfer2
    return mock_spi


def test_adxl335_driver_integrates_with_sampler():
    """ADXL335Driver can be used in place of fake_drivers for the vibration channel."""
    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 200, 1: 100, 2: 100})

    original_spidev = adxl335_module.spidev
    try:
        adxl335_module.spidev = mock_spidev

        fake_values = {
            "temperature": 26.0,
            "vibration": 0.03,  # placeholder; will be replaced
            "pressure": 1013.0,
            "humidity": 45.0,
            "gas": 150.0,
            "current": 0.0,
        }
        drivers = fake_drivers(fake_values)
        drivers["vibration"] = ADXL335Driver()

        sampler = Sampler(device_id="pump-01", drivers=drivers)

        # First sample establishes the vibration baseline (0.0 g)
        result1 = sampler.sample_once()
        assert result1.healthy is True
        assert result1.frame.sensors.vibration == 0.0

        # Second sample: X moves by +50 counts
        mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 250, 1: 100, 2: 100})
        result2 = sampler.sample_once()
        assert result2.healthy is True
        assert result2.frame is not None
        assert result2.frame.sample_seq == 1

        sensors = result2.frame.sensors
        assert sensors.temperature == 26.0
        assert sensors.vibration == pytest.approx(50 * _G_PER_COUNT)  # from real ADXL335 driver
        assert sensors.pressure == 1013.0
        assert sensors.humidity == 45.0
        assert sensors.gas == 150.0
        assert sensors.current == 0.0
    finally:
        adxl335_module.spidev = original_spidev


def test_adxl335_driver_unhealthy_read_propagates_through_sampler():
    """If ADXL335 read fails (SPI error), sampler returns no frame (unhealthy tick)."""
    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value.open.side_effect = OSError("SPI bus not available")

    original_spidev = adxl335_module.spidev
    try:
        adxl335_module.spidev = mock_spidev

        fake_values = {
            "temperature": 26.0,
            "vibration": 0.03,
            "pressure": 1013.0,
            "humidity": 45.0,
            "gas": 150.0,
            "current": 0.0,
        }
        drivers = fake_drivers(fake_values)
        drivers["vibration"] = ADXL335Driver()

        sampler = Sampler(device_id="pump-01", drivers=drivers)
        result = sampler.sample_once()

        assert result.healthy is False
        assert result.frame is None
        assert result.readings["vibration"].healthy is False
        assert result.readings["vibration"].value is None
    finally:
        adxl335_module.spidev = original_spidev
