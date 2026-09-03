"""Real DS18B20 driver tests (P1 · C1) — hardware-free using a fake sysfs tree.

Tests DS18B20TemperatureReader / ds18b20_raw_read / DS18B20Driver against real
files under pytest's tmp_path, mimicking the kernel w1-therm sysfs layout — no
mocking needed since the "hardware interface" here is plain file I/O.

Scaling: w1_slave's `t=<millidegrees>` is already CRC-validated and
unit-converted by the kernel (divide by 1000 for °C), confirmed against a
physical DS18B20 on Raspberry Pi 5 (t=27750 -> 27.75°C).
"""

from __future__ import annotations

import pytest

from edge.drivers.ds18b20 import (
    DS18B20Driver,
    DS18B20TemperatureReader,
    _find_w1_device,
    ds18b20_raw_read,
)


def _w1_slave_text(*, crc_ok: bool = True, millidegrees: int | None = 27750) -> str:
    """Build realistic w1_slave file content."""
    crc_word = "YES" if crc_ok else "NO"
    line1 = f"4e 01 4b 46 7f ff 0c 10 5d : crc=5d {crc_word}"
    if millidegrees is None:
        line2 = "4e 01 4b 46 7f ff 0c 10 5d"  # no t= field
    else:
        line2 = f"4e 01 4b 46 7f ff 0c 10 5d t={millidegrees}"
    return f"{line1}\n{line2}\n"


def _make_device_dir(path, *, crc_ok: bool = True, millidegrees: int | None = 27750) -> None:
    """Create a fake 1-Wire device directory with a w1_slave file."""
    path.mkdir(parents=True)
    (path / "w1_slave").write_text(_w1_slave_text(crc_ok=crc_ok, millidegrees=millidegrees))


class TestFindW1Device:
    """Test DS18B20 (family-code 28-) auto-discovery."""

    def test_finds_matching_device(self, tmp_path):
        _make_device_dir(tmp_path / "28-00000055547c")
        found = _find_w1_device(tmp_path, "28-")
        assert found == tmp_path / "28-00000055547c"

    def test_skips_non_matching_devices(self, tmp_path):
        """Other 1-Wire devices (different family code) are present."""
        (tmp_path / "00-000000000000").mkdir(parents=True)
        _make_device_dir(tmp_path / "28-00000055547c")
        found = _find_w1_device(tmp_path, "28-")
        assert found == tmp_path / "28-00000055547c"

    def test_returns_first_match_sorted_when_multiple_probes(self, tmp_path):
        _make_device_dir(tmp_path / "28-00000055547c")
        _make_device_dir(tmp_path / "28-00000099999a")
        found = _find_w1_device(tmp_path, "28-")
        assert found == tmp_path / "28-00000055547c"

    def test_raises_when_no_matching_device(self, tmp_path):
        (tmp_path / "00-000000000000").mkdir(parents=True)
        with pytest.raises(OSError, match="no 1-Wire device matching"):
            _find_w1_device(tmp_path, "28-")

    def test_raises_when_root_empty(self, tmp_path):
        with pytest.raises(OSError, match="no 1-Wire device matching"):
            _find_w1_device(tmp_path, "28-")


class TestDS18B20TemperatureReader:
    """Test the low-level sysfs reader, CRC check, and °C conversion."""

    def test_read_temperature_c_typical(self, tmp_path):
        """t=27750 -> 27.75°C — matches physical Pi 5 reading."""
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, millidegrees=27750)
        reader = DS18B20TemperatureReader(device_path=device_dir)
        assert reader.read_temperature_c() == pytest.approx(27.75)

    def test_read_temperature_c_via_auto_discovery(self, tmp_path):
        _make_device_dir(tmp_path / "28-00000055547c", millidegrees=19875)
        reader = DS18B20TemperatureReader(w1_root=tmp_path)
        assert reader.read_temperature_c() == pytest.approx(19.875)

    def test_auto_discovery_cached_after_first_read(self, tmp_path):
        """Device path is resolved once, not re-globbed on every read."""
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, millidegrees=25000)
        reader = DS18B20TemperatureReader(w1_root=tmp_path)
        reader.read_temperature_c()
        assert reader._resolved_path == device_dir
        assert reader.read_temperature_c() == pytest.approx(25.0)

    def test_read_negative_temperature(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, millidegrees=-5250)
        reader = DS18B20TemperatureReader(device_path=device_dir)
        assert reader.read_temperature_c() == pytest.approx(-5.25)

    def test_read_zero_temperature(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, millidegrees=0)
        reader = DS18B20TemperatureReader(device_path=device_dir)
        assert reader.read_temperature_c() == 0.0

    def test_failed_crc_raises(self, tmp_path):
        """Kernel-reported CRC=NO must not be trusted."""
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, crc_ok=False, millidegrees=27750)
        reader = DS18B20TemperatureReader(device_path=device_dir)
        with pytest.raises(OSError, match="CRC check failed"):
            reader.read_temperature_c()

    def test_missing_temperature_field_raises(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, millidegrees=None)
        reader = DS18B20TemperatureReader(device_path=device_dir)
        with pytest.raises(OSError, match="no temperature reading found"):
            reader.read_temperature_c()

    def test_malformed_single_line_raises(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        device_dir.mkdir(parents=True)
        (device_dir / "w1_slave").write_text("garbage single line\n")
        reader = DS18B20TemperatureReader(device_path=device_dir)
        with pytest.raises(OSError, match="malformed w1_slave content"):
            reader.read_temperature_c()

    def test_missing_w1_slave_file_raises(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        device_dir.mkdir(parents=True)  # no w1_slave file
        reader = DS18B20TemperatureReader(device_path=device_dir)
        with pytest.raises(OSError, match="failed to read"):
            reader.read_temperature_c()

    def test_missing_device_dir_raises(self, tmp_path):
        reader = DS18B20TemperatureReader(device_path=tmp_path / "28-nonexistent")
        with pytest.raises(OSError, match="failed to read"):
            reader.read_temperature_c()

    def test_no_device_found_raises(self, tmp_path):
        """No DS18B20 present anywhere under the root (overlay not enabled / not wired)."""
        reader = DS18B20TemperatureReader(w1_root=tmp_path)
        with pytest.raises(OSError, match="no 1-Wire device matching"):
            reader.read_temperature_c()


class TestDS18B20RawRead:
    """Test the ds18b20_raw_read factory."""

    def test_returns_callable(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir)
        raw_read = ds18b20_raw_read(device_path=device_dir)
        assert callable(raw_read)

    def test_invokes_reader(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, millidegrees=27750)
        raw_read = ds18b20_raw_read(device_path=device_dir)
        assert raw_read() == pytest.approx(27.75)

    def test_failure_raises(self, tmp_path):
        """Caller must wrap in Sensor to convert to unhealthy."""
        raw_read = ds18b20_raw_read(device_path=tmp_path / "28-nonexistent")
        with pytest.raises(OSError):
            raw_read()


class TestDS18B20Driver:
    """Test the full SensorDriver implementation."""

    def test_driver_read_healthy(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, millidegrees=27750)
        driver = DS18B20Driver(device_path=device_dir)
        reading = driver.read()

        assert reading.healthy is True
        assert reading.value == pytest.approx(27.75)
        assert reading.unit == "°C"
        assert reading.ts is not None

    def test_driver_read_missing_device_returns_unhealthy(self, tmp_path):
        """Driver read returns unhealthy Reading on sysfs failure (never raises)."""
        driver = DS18B20Driver(device_path=tmp_path / "28-nonexistent")
        reading = driver.read()

        assert reading.healthy is False
        assert reading.value is None
        assert reading.unit == "°C"
        assert reading.ts is not None

    def test_driver_read_failed_crc_returns_unhealthy(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, crc_ok=False)
        driver = DS18B20Driver(device_path=device_dir)
        reading = driver.read()

        assert reading.healthy is False
        assert reading.value is None

    def test_driver_read_no_overlay_returns_unhealthy(self, tmp_path):
        """Auto-discovery finds nothing (overlay not loaded) -> unhealthy, no raise."""
        driver = DS18B20Driver(w1_root=tmp_path)
        reading = driver.read()

        assert reading.healthy is False
        assert reading.value is None

    def test_driver_read_recovers_after_failure(self, tmp_path):
        """Driver read recovers after a transient failure (resilient)."""
        device_dir = tmp_path / "28-00000055547c"
        driver = DS18B20Driver(device_path=device_dir)

        # First read fails: device dir doesn't exist yet
        reading1 = driver.read()
        assert reading1.healthy is False

        # Device now appears (e.g. overlay finished loading)
        _make_device_dir(device_dir, millidegrees=22125)
        reading2 = driver.read()
        assert reading2.healthy is True
        assert reading2.value == pytest.approx(22.125)

    def test_driver_implements_sensor_driver(self, tmp_path):
        from edge.drivers.base import SensorDriver

        driver = DS18B20Driver(device_path=tmp_path / "28-nonexistent")
        assert isinstance(driver, SensorDriver)

    def test_driver_reading_shape(self, tmp_path):
        device_dir = tmp_path / "28-00000055547c"
        _make_device_dir(device_dir, millidegrees=27750)
        driver = DS18B20Driver(device_path=device_dir)
        reading = driver.read()

        assert hasattr(reading, "value")
        assert hasattr(reading, "unit")
        assert hasattr(reading, "ts")
        assert hasattr(reading, "healthy")
        assert isinstance(reading.as_dict(), dict)
        assert set(reading.as_dict().keys()) == {"value", "unit", "ts", "healthy"}
