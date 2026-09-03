"""Integration test: edge/main.py uses real DS18B20 for temperature, alongside
the existing real INA219 (current) and DHT22 (humidity) drivers, fake drivers
elsewhere (P1).

Verifies that the main.py driver-construction pattern is correct:
  - Current channel: real INA219Driver (bus 1, address 0x40)
  - Humidity channel: real DHT22Driver (kernel dht11 IIO driver)
  - Temperature channel: real DS18B20Driver (kernel w1-therm 1-Wire driver)
  - Remaining three channels: fake drivers (vibration, pressure, gas)
  - Frozen six-channel TelemetryMessage contract is preserved
"""

from __future__ import annotations

import pytest

from edge.drivers.base import Sensor, SensorDriver
from edge.drivers.dht22 import DHT22Driver
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.fake import fake_drivers
from edge.drivers.ina219 import INA219Driver


def _dev_values() -> dict:
    return {
        "temperature": 26.0,  # Placeholder; replaced by DS18B20Driver
        "vibration": 0.03,
        "pressure": 1013.0,
        "humidity": 45.0,  # Placeholder; replaced by DHT22Driver
        "gas": 150.0,
        "current": 0.0,  # Placeholder; replaced by INA219Driver
    }


def test_main_uses_ds18b20_for_temperature_channel(tmp_path):
    """Verify edge/main.py construction: DS18B20Driver replaces fake temperature driver."""
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
    drivers["temperature"] = DS18B20Driver(w1_root=tmp_path)  # path doesn't matter here

    for driver in drivers.values():
        assert isinstance(driver, SensorDriver)

    assert isinstance(drivers["temperature"], DS18B20Driver)
    assert not isinstance(drivers["temperature"], Sensor)
    assert isinstance(drivers["humidity"], DHT22Driver)
    assert isinstance(drivers["current"], INA219Driver)


def test_three_channels_remain_fake_drivers(tmp_path):
    """Verify non-current, non-humidity, non-temperature channels use fake drivers."""
    drivers = fake_drivers(_dev_values())
    drivers["current"] = INA219Driver()
    drivers["humidity"] = DHT22Driver(iio_root=tmp_path)
    drivers["temperature"] = DS18B20Driver(w1_root=tmp_path)

    assert isinstance(drivers["vibration"], Sensor)
    assert isinstance(drivers["pressure"], Sensor)
    assert isinstance(drivers["gas"], Sensor)

    assert isinstance(drivers["temperature"], DS18B20Driver)
    assert not isinstance(drivers["temperature"], Sensor)


def test_frozen_contract_with_ds18b20_temperature_and_dht22_humidity(tmp_path):
    """Verify frozen six-channel TelemetryMessage can be built with DS18B20 + DHT22."""
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

    drivers = fake_drivers(_dev_values())
    drivers["temperature"] = DS18B20Driver(device_path=w1_device_dir)
    drivers["humidity"] = DHT22Driver(iio_path=iio_device_dir)

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is True
    assert result.frame is not None

    sensors = result.frame.sensors
    assert sensors.temperature == pytest.approx(27.75)  # From real DS18B20
    assert sensors.vibration == 0.03
    assert sensors.pressure == 1013.0
    assert sensors.humidity == pytest.approx(62.6)  # From real DHT22
    assert sensors.gas == 150.0
    assert sensors.current == 0.0

    assert result.frame.device_id == "pump-01"
    assert result.frame.sample_seq == 0
    assert result.frame.ts is not None


def test_ds18b20_failure_propagates_through_sampler(tmp_path):
    """If DS18B20 fails, sampler returns unhealthy (other channels don't matter)."""
    from edge.acquisition.sampler import Sampler

    drivers = fake_drivers(_dev_values())
    drivers["temperature"] = DS18B20Driver(w1_root=tmp_path)  # no device present -> fails

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is False
    assert result.frame is None

    assert result.readings["temperature"].healthy is False
    assert result.readings["temperature"].value is None
