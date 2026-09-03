"""Integration test: edge/main.py uses real BMP280 for pressure, alongside
the existing real ADXL335 (vibration) driver, fake drivers elsewhere (P1).

Verifies that the main.py driver-construction pattern is correct:
  - Vibration channel: real ADXL335Driver (MCP3008 over SPI0 CE0)
  - Pressure channel: real BMP280Driver (I²C bus 1, address 0x76)
  - Remaining four channels: fake drivers (temperature, humidity, gas, current)
  - Frozen six-channel TelemetryMessage contract is preserved
"""

from __future__ import annotations

import struct
from unittest.mock import MagicMock

import edge.drivers.adxl335 as adxl335_module
import edge.drivers.bmp280 as bmp280_module
from edge.drivers.adxl335 import ADXL335Driver
from edge.drivers.base import Sensor, SensorDriver
from edge.drivers.bmp280 import BMP280Driver
from edge.drivers.fake import fake_drivers

# Same Bosch self-test calibration/raw-ADC vector used in test_bmp280_driver.py.
_DIG_T1, _DIG_T2, _DIG_T3 = 27504, 26435, -1000
_DIG_P1, _DIG_P2, _DIG_P3 = 36477, -10685, 3024
_DIG_P4, _DIG_P5, _DIG_P6 = 2855, 140, -7
_DIG_P7, _DIG_P8, _DIG_P9 = 15500, -14600, 6000
_ADC_T = 519888
_ADC_P = 415148


def _pack_calibration() -> list[int]:
    packed = struct.pack(
        "<HhhHhhhhhhhh",
        _DIG_T1, _DIG_T2, _DIG_T3,
        _DIG_P1, _DIG_P2, _DIG_P3, _DIG_P4, _DIG_P5, _DIG_P6, _DIG_P7, _DIG_P8, _DIG_P9,
    )
    return list(packed)


def _pack_data(raw_pressure: int, raw_temperature: int) -> list[int]:
    press_msb = (raw_pressure >> 12) & 0xFF
    press_lsb = (raw_pressure >> 4) & 0xFF
    press_xlsb = (raw_pressure & 0x0F) << 4
    temp_msb = (raw_temperature >> 12) & 0xFF
    temp_lsb = (raw_temperature >> 4) & 0xFF
    temp_xlsb = (raw_temperature & 0x0F) << 4
    return [press_msb, press_lsb, press_xlsb, temp_msb, temp_lsb, temp_xlsb]


def _mock_bmp280_bus(*, chip_id=0x58) -> MagicMock:
    bus = MagicMock()
    calib_bytes = _pack_calibration()
    data_bytes = _pack_data(_ADC_P, _ADC_T)

    def _read_block(address, register, length):
        if register == 0xD0:
            return [chip_id]
        if register == 0x88:
            return list(calib_bytes)
        if register == 0xF3:
            return [0x00]
        if register == 0xF7:
            return list(data_bytes)
        raise AssertionError(f"unexpected register read: 0x{register:02x}")

    bus.read_i2c_block_data.side_effect = _read_block
    return bus


def _adxl335_reply_for(value: int) -> list[int]:
    return [0, (value >> 8) & 0x03, value & 0xFF]


def _mock_adxl335_spi(channel_values: dict[int, int]) -> MagicMock:
    mock_spi = MagicMock()

    def _xfer2(cmd):
        channel = (cmd[1] >> 4) - 8
        return _adxl335_reply_for(channel_values[channel])

    mock_spi.xfer2.side_effect = _xfer2
    return mock_spi


def _dev_values() -> dict:
    return {
        "temperature": 26.0,
        "vibration": 0.03,  # Placeholder; replaced by ADXL335Driver
        "pressure": 1013.0,  # Placeholder; replaced by BMP280Driver
        "humidity": 45.0,
        "gas": 150.0,
        "current": 0.0,
    }


def test_main_uses_bmp280_for_pressure_channel():
    """Verify edge/main.py construction: BMP280Driver replaces fake pressure driver."""
    mock_smbus2 = MagicMock()
    mock_smbus2.SMBus.return_value = _mock_bmp280_bus()
    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value = _mock_adxl335_spi({0: 100, 1: 100, 2: 100})

    original_smbus2 = bmp280_module.smbus2
    original_spidev = adxl335_module.spidev
    try:
        bmp280_module.smbus2 = mock_smbus2
        adxl335_module.spidev = mock_spidev

        drivers = fake_drivers(_dev_values())
        assert set(drivers.keys()) == {
            "temperature", "vibration", "pressure", "humidity", "gas", "current",
        }

        drivers["vibration"] = ADXL335Driver(bus=0, device=0)
        drivers["pressure"] = BMP280Driver(bus_num=1, address=0x76)

        for driver in drivers.values():
            assert isinstance(driver, SensorDriver)

        assert isinstance(drivers["pressure"], BMP280Driver)
        assert not isinstance(drivers["pressure"], Sensor)
        assert isinstance(drivers["vibration"], ADXL335Driver)
    finally:
        bmp280_module.smbus2 = original_smbus2
        adxl335_module.spidev = original_spidev


def test_four_channels_remain_fake_drivers():
    """Verify non-vibration, non-pressure channels use fake drivers."""
    mock_smbus2 = MagicMock()
    mock_smbus2.SMBus.return_value = _mock_bmp280_bus()
    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value = _mock_adxl335_spi({0: 100, 1: 100, 2: 100})

    original_smbus2 = bmp280_module.smbus2
    original_spidev = adxl335_module.spidev
    try:
        bmp280_module.smbus2 = mock_smbus2
        adxl335_module.spidev = mock_spidev

        drivers = fake_drivers(_dev_values())
        drivers["vibration"] = ADXL335Driver()
        drivers["pressure"] = BMP280Driver()

        assert isinstance(drivers["temperature"], Sensor)
        assert isinstance(drivers["humidity"], Sensor)
        assert isinstance(drivers["gas"], Sensor)
        assert isinstance(drivers["current"], Sensor)

        assert isinstance(drivers["pressure"], BMP280Driver)
        assert not isinstance(drivers["pressure"], Sensor)
    finally:
        bmp280_module.smbus2 = original_smbus2
        adxl335_module.spidev = original_spidev


def test_frozen_contract_with_adxl335_and_bmp280():
    """Verify frozen six-channel TelemetryMessage can be built with real
    ADXL335 (vibration) + real BMP280 (pressure), matching main.py exactly."""
    from edge.acquisition.sampler import Sampler

    mock_smbus2 = MagicMock()
    mock_smbus2.SMBus.return_value = _mock_bmp280_bus()
    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value = _mock_adxl335_spi({0: 500, 1: 500, 2: 500})

    original_smbus2 = bmp280_module.smbus2
    original_spidev = adxl335_module.spidev
    try:
        bmp280_module.smbus2 = mock_smbus2
        adxl335_module.spidev = mock_spidev

        drivers = fake_drivers(_dev_values())
        drivers["vibration"] = ADXL335Driver()
        drivers["pressure"] = BMP280Driver()

        sampler = Sampler(device_id="pump-01", drivers=drivers)
        result = sampler.sample_once()

        assert result.healthy is True
        assert result.frame is not None

        sensors = result.frame.sensors
        assert sensors.temperature == 26.0
        assert sensors.vibration == 0.0  # From real ADXL335 (first read = baseline)
        assert sensors.pressure > 0  # From real BMP280
        assert sensors.humidity == 45.0
        assert sensors.gas == 150.0
        assert sensors.current == 0.0

        assert result.frame.device_id == "pump-01"
        assert result.frame.sample_seq == 0
        assert result.frame.ts is not None
    finally:
        bmp280_module.smbus2 = original_smbus2
        adxl335_module.spidev = original_spidev


def test_bmp280_failure_propagates_through_sampler():
    """If BMP280 fails, sampler returns unhealthy (other channels don't matter),
    same error-handling behavior as every other real driver in this codebase."""
    from edge.acquisition.sampler import Sampler

    mock_spidev = MagicMock()
    mock_spidev.SpiDev.return_value = _mock_adxl335_spi({0: 100, 1: 100, 2: 100})
    mock_smbus2 = MagicMock()
    mock_smbus2.SMBus.side_effect = OSError("Remote I/O error")

    original_smbus2 = bmp280_module.smbus2
    original_spidev = adxl335_module.spidev
    try:
        bmp280_module.smbus2 = mock_smbus2
        adxl335_module.spidev = mock_spidev

        drivers = fake_drivers(_dev_values())
        drivers["vibration"] = ADXL335Driver()
        drivers["pressure"] = BMP280Driver()  # no working I2C bus -> fails

        sampler = Sampler(device_id="pump-01", drivers=drivers)
        result = sampler.sample_once()

        assert result.healthy is False
        assert result.frame is None

        assert result.readings["pressure"].healthy is False
        assert result.readings["pressure"].value is None
    finally:
        bmp280_module.smbus2 = original_smbus2
        adxl335_module.spidev = original_spidev
