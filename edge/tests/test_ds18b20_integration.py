"""DS18B20 hardware driver integration with Sampler and AcquisitionRuntime (P1 · C1→C2).

Demonstrates the DS18B20Driver's integration with the real C2 Sampler,
assembling a frozen TelemetryMessage. No physical hardware; a fake sysfs
tree (tmp_path) stands in for the kernel w1-therm 1-Wire device.
"""

from __future__ import annotations

import pytest

from edge.acquisition.sampler import Sampler
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.fake import fake_drivers


def _make_w1_device(root, *, millidegrees: int) -> None:
    device_dir = root / "28-00000055547c"
    device_dir.mkdir(parents=True)
    (device_dir / "w1_slave").write_text(
        f"4e 01 4b 46 7f ff 0c 10 5d : crc=5d YES\n"
        f"4e 01 4b 46 7f ff 0c 10 5d t={millidegrees}\n"
    )


def test_ds18b20_driver_integrates_with_sampler(tmp_path):
    """DS18B20Driver can be used in place of fake_drivers for the temperature channel."""
    _make_w1_device(tmp_path, millidegrees=27750)  # -> 27.75°C

    fake_values = {
        "temperature": 26.0,  # placeholder; will be replaced
        "vibration": 0.03,
        "pressure": 1013.0,
        "humidity": 45.0,
        "gas": 150.0,
        "current": 0.0,
    }
    drivers = fake_drivers(fake_values)
    drivers["temperature"] = DS18B20Driver(w1_root=tmp_path)

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is True
    assert result.frame is not None
    assert result.frame.device_id == "pump-01"
    assert result.frame.sample_seq == 0

    sensors = result.frame.sensors
    assert sensors.temperature == pytest.approx(27.75)  # from real DS18B20 driver
    assert sensors.vibration == 0.03
    assert sensors.pressure == 1013.0
    assert sensors.humidity == 45.0
    assert sensors.gas == 150.0
    assert sensors.current == 0.0


def test_ds18b20_driver_unhealthy_read_propagates_through_sampler(tmp_path):
    """If DS18B20 read fails, sampler returns no frame (unhealthy tick)."""
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
    drivers["temperature"] = DS18B20Driver(w1_root=tmp_path)

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is False
    assert result.frame is None
    assert result.readings["temperature"].healthy is False
    assert result.readings["temperature"].value is None


def test_ds18b20_driver_failed_crc_propagates_through_sampler(tmp_path):
    """A DS18B20 CRC failure (noisy 1-Wire read) also yields an unhealthy tick."""
    device_dir = tmp_path / "28-00000055547c"
    device_dir.mkdir(parents=True)
    (device_dir / "w1_slave").write_text(
        "4e 01 4b 46 7f ff 0c 10 5d : crc=5d NO\n"
        "4e 01 4b 46 7f ff 0c 10 5d t=27750\n"
    )

    fake_values = {
        "temperature": 26.0,
        "vibration": 0.03,
        "pressure": 1013.0,
        "humidity": 45.0,
        "gas": 150.0,
        "current": 0.0,
    }
    drivers = fake_drivers(fake_values)
    drivers["temperature"] = DS18B20Driver(w1_root=tmp_path)

    sampler = Sampler(device_id="pump-01", drivers=drivers)
    result = sampler.sample_once()

    assert result.healthy is False
    assert result.frame is None
    assert result.readings["temperature"].healthy is False
