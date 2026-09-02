"""DHT22 hardware driver integration with Sampler and AcquisitionRuntime (P1 · C1→C2).

Demonstrates the DHT22Driver's integration with the real C2 Sampler,
assembling a frozen TelemetryMessage. No physical hardware; a fake sysfs
tree (tmp_path) stands in for the kernel dht11 IIO device.
"""

from __future__ import annotations

import pytest

from edge.acquisition.sampler import Sampler
from edge.drivers.dht22 import DHT22Driver
from edge.drivers.fake import fake_drivers


def _make_iio_device(root, name: str, humidity_raw: str) -> None:
    device_dir = root / "device0"
    device_dir.mkdir(parents=True)
    (device_dir / "name").write_text(name)
    (device_dir / "in_humidityrelative_input").write_text(humidity_raw)


def test_dht22_driver_integrates_with_sampler(tmp_path):
    """DHT22Driver can be used in place of fake_drivers for the humidity channel."""
    _make_iio_device(tmp_path, "dht11@11", "62600")  # -> 62.6 %RH (milli-percent)

    fake_values = {
        "temperature": 26.0,
        "vibration": 0.03,
        "pressure": 1013.0,
        "humidity": 45.0,  # placeholder; will be replaced
        "gas": 150.0,
        "current": 0.0,
    }
    drivers = fake_drivers(fake_values)
    drivers["humidity"] = DHT22Driver(iio_path=tmp_path / "device0")

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is True
    assert result.frame is not None
    assert result.frame.device_id == "pump-01"
    assert result.frame.sample_seq == 0

    sensors = result.frame.sensors
    assert sensors.temperature == 26.0
    assert sensors.vibration == 0.03
    assert sensors.pressure == 1013.0
    assert sensors.humidity == pytest.approx(62.6)  # from real DHT22 driver
    assert sensors.gas == 150.0
    assert sensors.current == 0.0


def test_dht22_driver_unhealthy_read_propagates_through_sampler(tmp_path):
    """If DHT22 read fails, sampler returns no frame (unhealthy tick)."""
    fake_values = {
        "temperature": 26.0,
        "vibration": 0.03,
        "pressure": 1013.0,
        "humidity": 45.0,
        "gas": 150.0,
        "current": 0.0,
    }
    drivers = fake_drivers(fake_values)
    # No sysfs device exists under tmp_path -> read fails
    drivers["humidity"] = DHT22Driver(iio_root=tmp_path)

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is False
    assert result.frame is None
    assert result.readings["humidity"].healthy is False
    assert result.readings["humidity"].value is None
