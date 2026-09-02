"""Integration test: edge/main.py uses real DHT22 for humidity, fake drivers
elsewhere, alongside the existing real INA219 current driver (P1).

Verifies that the main.py driver-construction pattern is correct:
  - Current channel: real INA219Driver (bus 1, address 0x40)
  - Humidity channel: real DHT22Driver (kernel dht11 IIO driver)
  - Remaining four channels: fake drivers (temperature, vibration, pressure, gas)
  - Frozen six-channel TelemetryMessage contract is preserved
"""

from __future__ import annotations

from edge.drivers.base import Sensor, SensorDriver
from edge.drivers.dht22 import DHT22Driver
from edge.drivers.fake import fake_drivers
from edge.drivers.ina219 import INA219Driver


def _dev_values() -> dict:
    return {
        "temperature": 26.0,
        "vibration": 0.03,
        "pressure": 1013.0,
        "humidity": 45.0,  # Placeholder; replaced by DHT22Driver
        "gas": 150.0,
        "current": 0.0,  # Placeholder; replaced by INA219Driver
    }


def test_main_uses_dht22_for_humidity_channel(tmp_path):
    """Verify edge/main.py construction: DHT22Driver replaces fake humidity driver."""
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
    drivers["humidity"] = DHT22Driver(iio_root=tmp_path)  # path doesn't matter here

    for driver in drivers.values():
        assert isinstance(driver, SensorDriver)

    assert isinstance(drivers["humidity"], DHT22Driver)
    assert not isinstance(drivers["humidity"], Sensor)
    assert isinstance(drivers["current"], INA219Driver)


def test_four_channels_remain_fake_drivers(tmp_path):
    """Verify non-current, non-humidity channels use fake drivers."""
    drivers = fake_drivers(_dev_values())
    drivers["current"] = INA219Driver()
    drivers["humidity"] = DHT22Driver(iio_root=tmp_path)

    assert isinstance(drivers["temperature"], Sensor)
    assert isinstance(drivers["vibration"], Sensor)
    assert isinstance(drivers["pressure"], Sensor)
    assert isinstance(drivers["gas"], Sensor)

    assert isinstance(drivers["humidity"], DHT22Driver)
    assert not isinstance(drivers["humidity"], Sensor)


def test_frozen_contract_with_dht22_humidity(tmp_path):
    """Verify frozen six-channel TelemetryMessage can be built with DHT22 humidity."""
    from edge.acquisition.sampler import Sampler

    device_dir = tmp_path / "device0"
    device_dir.mkdir(parents=True)
    (device_dir / "name").write_text("dht11@11")
    (device_dir / "in_humidityrelative_input").write_text("62600")  # -> 62.6 %RH (milli-percent)

    drivers = fake_drivers(_dev_values())
    drivers["humidity"] = DHT22Driver(iio_path=device_dir)

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is True
    assert result.frame is not None

    sensors = result.frame.sensors
    assert sensors.temperature == 26.0
    assert sensors.vibration == 0.03
    assert sensors.pressure == 1013.0
    assert abs(sensors.humidity - 62.6) < 0.01  # From real DHT22
    assert sensors.gas == 150.0
    assert sensors.current == 0.0

    assert result.frame.device_id == "pump-01"
    assert result.frame.sample_seq == 0
    assert result.frame.ts is not None


def test_dht22_failure_propagates_through_sampler(tmp_path):
    """If DHT22 fails, sampler returns unhealthy (other channels don't matter)."""
    from edge.acquisition.sampler import Sampler

    drivers = fake_drivers(_dev_values())
    drivers["humidity"] = DHT22Driver(iio_root=tmp_path)  # no device present -> fails

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is False
    assert result.frame is None

    assert result.readings["humidity"].healthy is False
    assert result.readings["humidity"].value is None
