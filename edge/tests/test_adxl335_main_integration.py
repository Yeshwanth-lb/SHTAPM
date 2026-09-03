"""Integration test: edge/main.py uses real ADXL335 for vibration, alongside
the existing real INA219 (current), DHT22 (humidity), and DS18B20
(temperature) drivers, fake drivers for pressure/gas (P1).

Verifies that the main.py driver-construction pattern is correct:
  - Current channel: real INA219Driver (bus 1, address 0x40)
  - Humidity channel: real DHT22Driver (kernel dht11 IIO driver)
  - Temperature channel: real DS18B20Driver (kernel w1-therm 1-Wire driver)
  - Vibration channel: real ADXL335Driver (MCP3008 over SPI0 CE0)
  - Remaining two channels: fake drivers (pressure, gas)
  - Frozen six-channel TelemetryMessage contract is preserved
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import edge.drivers.adxl335 as adxl335_module
from edge.drivers.adxl335 import ADXL335Driver
from edge.drivers.base import Sensor, SensorDriver
from edge.drivers.dht22 import DHT22Driver
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.fake import fake_drivers
from edge.drivers.ina219 import INA219Driver

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


def _dev_values() -> dict:
    return {
        "temperature": 26.0,  # Placeholder; replaced by DS18B20Driver
        "vibration": 0.03,  # Placeholder; replaced by ADXL335Driver
        "pressure": 1013.0,
        "humidity": 45.0,  # Placeholder; replaced by DHT22Driver
        "gas": 150.0,
        "current": 0.0,  # Placeholder; replaced by INA219Driver
    }


def test_main_uses_adxl335_for_vibration_channel(tmp_path):
    """Verify edge/main.py construction: ADXL335Driver replaces fake vibration driver."""
    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 100, 1: 100, 2: 100})

    original_spidev = adxl335_module.spidev
    try:
        adxl335_module.spidev = mock_spidev

        drivers = fake_drivers(_dev_values())
        assert set(drivers.keys()) == {
            "temperature",
            "vibration",
            "pressure",
            "humidity",
            "gas",
            "current",
        }

        drivers["current"] = INA219Driver(
            bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
        )
        drivers["humidity"] = DHT22Driver(iio_root=tmp_path)
        drivers["temperature"] = DS18B20Driver(w1_root=tmp_path)
        drivers["vibration"] = ADXL335Driver(bus=0, device=0)

        for driver in drivers.values():
            assert isinstance(driver, SensorDriver)

        assert isinstance(drivers["vibration"], ADXL335Driver)
        assert not isinstance(drivers["vibration"], Sensor)
        assert isinstance(drivers["temperature"], DS18B20Driver)
        assert isinstance(drivers["humidity"], DHT22Driver)
        assert isinstance(drivers["current"], INA219Driver)
    finally:
        adxl335_module.spidev = original_spidev


def test_two_channels_remain_fake_drivers(tmp_path):
    """Verify pressure/gas remain fake once all four hardware channels are real."""
    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 100, 1: 100, 2: 100})

    original_spidev = adxl335_module.spidev
    try:
        adxl335_module.spidev = mock_spidev

        drivers = fake_drivers(_dev_values())
        drivers["current"] = INA219Driver()
        drivers["humidity"] = DHT22Driver(iio_root=tmp_path)
        drivers["temperature"] = DS18B20Driver(w1_root=tmp_path)
        drivers["vibration"] = ADXL335Driver()

        assert isinstance(drivers["pressure"], Sensor)
        assert isinstance(drivers["gas"], Sensor)

        assert isinstance(drivers["vibration"], ADXL335Driver)
        assert not isinstance(drivers["vibration"], Sensor)
    finally:
        adxl335_module.spidev = original_spidev


def test_frozen_contract_with_all_four_real_drivers(tmp_path):
    """Verify frozen six-channel TelemetryMessage can be built with DS18B20 +
    DHT22 + ADXL335 (+ INA219 mocked via fake for simplicity here — INA219's
    own I2C mock is exercised in its own test suite)."""
    from edge.acquisition.sampler import Sampler

    w1_device_dir = tmp_path / "w1" / "28-00000055547c"
    w1_device_dir.mkdir(parents=True)
    (w1_device_dir / "w1_slave").write_text(
        "4e 01 4b 46 7f ff 0c 10 5d : crc=5d YES\n"
        "4e 01 4b 46 7f ff 0c 10 5d t=27750\n"
    )

    iio_device_dir = tmp_path / "iio" / "device0"
    iio_device_dir.mkdir(parents=True)
    (iio_device_dir / "name").write_text("dht11@11")
    (iio_device_dir / "in_humidityrelative_input").write_text("62600")

    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value = _mock_spi_for_channels({0: 500, 1: 500, 2: 500})

    original_spidev = adxl335_module.spidev
    try:
        adxl335_module.spidev = mock_spidev

        drivers = fake_drivers(_dev_values())
        drivers["temperature"] = DS18B20Driver(device_path=w1_device_dir)
        drivers["humidity"] = DHT22Driver(iio_path=iio_device_dir)
        drivers["vibration"] = ADXL335Driver()

        sampler = Sampler(device_id="pump-01", drivers=drivers)
        result = sampler.sample_once()

        assert result.healthy is True
        assert result.frame is not None

        sensors = result.frame.sensors
        assert sensors.temperature == pytest.approx(27.75)  # From real DS18B20
        assert sensors.vibration == 0.0  # From real ADXL335 (first read = baseline)
        assert sensors.pressure == 1013.0
        assert sensors.humidity == pytest.approx(62.6)  # From real DHT22
        assert sensors.gas == 150.0
        assert sensors.current == 0.0

        assert result.frame.device_id == "pump-01"
        assert result.frame.sample_seq == 0
        assert result.frame.ts is not None
    finally:
        adxl335_module.spidev = original_spidev


def test_adxl335_failure_propagates_through_sampler():
    """If ADXL335 fails, sampler returns unhealthy (other channels don't matter)."""
    from edge.acquisition.sampler import Sampler

    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value.open.side_effect = OSError("SPI bus not available")

    original_spidev = adxl335_module.spidev
    try:
        adxl335_module.spidev = mock_spidev

        drivers = fake_drivers(_dev_values())
        drivers["vibration"] = ADXL335Driver()

        sampler = Sampler(device_id="pump-01", drivers=drivers)
        result = sampler.sample_once()

        assert result.healthy is False
        assert result.frame is None

        assert result.readings["vibration"].healthy is False
        assert result.readings["vibration"].value is None
    finally:
        adxl335_module.spidev = original_spidev
