"""Real DHT22 driver tests (P1 · C1) — hardware-free using a fake sysfs tree.

Tests DHT22HumidityReader / dht22_raw_read / DHT22Driver against real files
under pytest's tmp_path, mimicking the kernel dht11 IIO sysfs layout — no
mocking needed since the "hardware interface" here is plain file I/O.

Scaling: in_humidityrelative_input is milli-percent per the IIO ABI (divide
by 1000), confirmed against a physical DHT22 on Raspberry Pi 5 (62600 raw ->
62.6 %RH). Device naming: the kernel's `name` attribute is observed as
`dht11@11` (`<driver>@<instance>`) on Raspberry Pi OS, not the bare `dht11`,
so discovery matches on the `dht11` prefix.

Auto-discovery tests need a directory literally named "iio:deviceN" (the real
Linux sysfs naming, colon included) — Windows filesystems reject ':' in
filenames, so those are skipped on Windows; the driver only ever runs on the
Pi (Linux) anyway. Tests that pass an explicit `iio_path` don't depend on the
literal name and run on every platform.
"""

from __future__ import annotations

import sys

import pytest

from edge.drivers.dht22 import (
    DHT22Driver,
    DHT22HumidityReader,
    _find_iio_device,
    _matches_driver,
    dht22_raw_read,
)

_skip_no_colon = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows disallows ':' in filenames; iio:deviceN dirs can't be created here",
)


def _make_device_dir(path, name: str, humidity_raw: str | None = None) -> None:
    """Create a fake IIO device directory at `path` with a `name` file and
    optionally an `in_humidityrelative_input` file (mirrors kernel sysfs)."""
    path.mkdir(parents=True)
    (path / "name").write_text(name)
    if humidity_raw is not None:
        (path / "in_humidityrelative_input").write_text(humidity_raw)


class TestMatchesDriver:
    """Test the dht11 / dht11@N name-matching predicate."""

    def test_exact_bare_name_matches(self):
        assert _matches_driver("dht11", "dht11") is True

    def test_instance_suffixed_name_matches(self):
        """Observed on Raspberry Pi OS: name is `dht11@11` (GPIO 17 -> pin 11)."""
        assert _matches_driver("dht11@11", "dht11") is True

    def test_other_instance_suffix_matches(self):
        assert _matches_driver("dht11@0", "dht11") is True

    def test_unrelated_name_does_not_match(self):
        assert _matches_driver("some_other_sensor", "dht11") is False

    def test_name_with_dht11_prefix_but_no_separator_does_not_match(self):
        """Guards against accidental substring collisions (e.g. `dht11xyz`)."""
        assert _matches_driver("dht11xyz", "dht11") is False


class TestFindIIODevice:
    """Test dht11 IIO device auto-discovery (real "iio:deviceN" naming)."""

    @_skip_no_colon
    def test_finds_bare_named_device(self, tmp_path):
        _make_device_dir(tmp_path / "iio:device0", "dht11", "62600")
        found = _find_iio_device(tmp_path, "dht11")
        assert found == tmp_path / "iio:device0"

    @_skip_no_colon
    def test_finds_instance_suffixed_device(self, tmp_path):
        """Real-world case: kernel name is `dht11@11`, not `dht11`."""
        _make_device_dir(tmp_path / "iio:device0", "dht11@11", "62600")
        found = _find_iio_device(tmp_path, "dht11")
        assert found == tmp_path / "iio:device0"

    @_skip_no_colon
    def test_skips_non_matching_devices_and_finds_correct_one(self, tmp_path):
        """Other IIO devices (e.g. an ADC) are present; dht11 is not device0."""
        _make_device_dir(tmp_path / "iio:device0", "some_other_sensor")
        _make_device_dir(tmp_path / "iio:device1", "dht11@11", "62600")
        found = _find_iio_device(tmp_path, "dht11")
        assert found == tmp_path / "iio:device1"

    @_skip_no_colon
    def test_raises_when_no_matching_device(self, tmp_path):
        _make_device_dir(tmp_path / "iio:device0", "some_other_sensor")
        with pytest.raises(OSError, match="no IIO device matching"):
            _find_iio_device(tmp_path, "dht11")

    def test_raises_when_root_empty(self, tmp_path):
        with pytest.raises(OSError, match="no IIO device matching"):
            _find_iio_device(tmp_path, "dht11")

    @_skip_no_colon
    def test_ignores_device_missing_name_file(self, tmp_path):
        """A device dir without a readable `name` file is skipped, not fatal."""
        (tmp_path / "iio:device0").mkdir(parents=True)
        _make_device_dir(tmp_path / "iio:device1", "dht11@11", "62600")
        found = _find_iio_device(tmp_path, "dht11")
        assert found == tmp_path / "iio:device1"


class TestDHT22HumidityReader:
    """Test the low-level sysfs reader and %RH conversion (milli-percent)."""

    def test_read_humidity_percent_typical(self, tmp_path):
        """62600 raw (milli-percent) -> 62.6 %RH — matches physical Pi 5 reading."""
        _make_device_dir(tmp_path / "device0", "dht11@11", "62600")
        reader = DHT22HumidityReader(iio_path=tmp_path / "device0")
        assert reader.read_humidity_percent() == pytest.approx(62.6)

    @_skip_no_colon
    def test_read_humidity_percent_via_auto_discovery(self, tmp_path):
        _make_device_dir(tmp_path / "iio:device0", "dht11@11", "60100")
        reader = DHT22HumidityReader(iio_root=tmp_path)
        assert reader.read_humidity_percent() == pytest.approx(60.1)

    @_skip_no_colon
    def test_auto_discovery_cached_after_first_read(self, tmp_path):
        """Device path is resolved once, not re-globbed on every read."""
        _make_device_dir(tmp_path / "iio:device0", "dht11@11", "30000")
        reader = DHT22HumidityReader(iio_root=tmp_path)
        reader.read_humidity_percent()
        assert reader._resolved_path == tmp_path / "iio:device0"
        # Second read still works from the cached path
        assert reader.read_humidity_percent() == pytest.approx(30.0)

    def test_read_zero_humidity(self, tmp_path):
        _make_device_dir(tmp_path / "device0", "dht11@11", "0")
        reader = DHT22HumidityReader(iio_path=tmp_path / "device0")
        assert reader.read_humidity_percent() == 0.0

    def test_missing_humidity_attr_raises(self, tmp_path):
        """Device directory exists but has no in_humidityrelative_input file."""
        _make_device_dir(tmp_path / "device0", "dht11@11")  # no humidity_raw
        reader = DHT22HumidityReader(iio_path=tmp_path / "device0")
        with pytest.raises(OSError, match="failed to read"):
            reader.read_humidity_percent()

    def test_missing_device_dir_raises(self, tmp_path):
        reader = DHT22HumidityReader(iio_path=tmp_path / "device99")
        with pytest.raises(OSError, match="failed to read"):
            reader.read_humidity_percent()

    def test_malformed_value_raises(self, tmp_path):
        """Driver returned non-numeric garbage (e.g. transient kernel glitch)."""
        _make_device_dir(tmp_path / "device0", "dht11@11", "not-a-number")
        reader = DHT22HumidityReader(iio_path=tmp_path / "device0")
        with pytest.raises(OSError, match="unexpected value"):
            reader.read_humidity_percent()

    @_skip_no_colon
    def test_no_device_found_raises(self, tmp_path):
        """No dht11 device present anywhere under the root (overlay not enabled)."""
        _make_device_dir(tmp_path / "iio:device0", "some_other_sensor")
        reader = DHT22HumidityReader(iio_root=tmp_path)
        with pytest.raises(OSError, match="no IIO device matching"):
            reader.read_humidity_percent()


class TestDHT22RawRead:
    """Test the dht22_raw_read factory."""

    def test_returns_callable(self, tmp_path):
        _make_device_dir(tmp_path / "device0", "dht11@11", "62600")
        raw_read = dht22_raw_read(iio_path=tmp_path / "device0")
        assert callable(raw_read)

    def test_invokes_reader(self, tmp_path):
        _make_device_dir(tmp_path / "device0", "dht11@11", "62600")
        raw_read = dht22_raw_read(iio_path=tmp_path / "device0")
        assert raw_read() == pytest.approx(62.6)

    def test_failure_raises(self, tmp_path):
        """Caller must wrap in Sensor to convert to unhealthy."""
        raw_read = dht22_raw_read(iio_path=tmp_path / "device0")
        with pytest.raises(OSError):
            raw_read()


class TestDHT22Driver:
    """Test the full SensorDriver implementation."""

    def test_driver_read_healthy(self, tmp_path):
        _make_device_dir(tmp_path / "device0", "dht11@11", "62600")
        driver = DHT22Driver(iio_path=tmp_path / "device0")
        reading = driver.read()

        assert reading.healthy is True
        assert reading.value == pytest.approx(62.6)
        assert reading.unit == "%"
        assert reading.ts is not None

    def test_driver_read_missing_device_returns_unhealthy(self, tmp_path):
        """Driver read returns unhealthy Reading on sysfs failure (never raises)."""
        driver = DHT22Driver(iio_path=tmp_path / "device0")
        reading = driver.read()

        assert reading.healthy is False
        assert reading.value is None
        assert reading.unit == "%"
        assert reading.ts is not None

    def test_driver_read_no_overlay_returns_unhealthy(self, tmp_path):
        """Auto-discovery finds nothing (overlay not loaded) -> unhealthy, no raise."""
        driver = DHT22Driver(iio_root=tmp_path)
        reading = driver.read()

        assert reading.healthy is False
        assert reading.value is None

    def test_driver_read_recovers_after_failure(self, tmp_path):
        """Driver read recovers after a transient failure (resilient)."""
        device_dir = tmp_path / "device0"
        driver = DHT22Driver(iio_path=device_dir)

        # First read fails: device dir doesn't exist yet
        reading1 = driver.read()
        assert reading1.healthy is False

        # Device now appears (e.g. overlay finished loading)
        _make_device_dir(device_dir, "dht11@11", "50000")
        reading2 = driver.read()
        assert reading2.healthy is True
        assert reading2.value == pytest.approx(50.0)

    def test_driver_implements_sensor_driver(self, tmp_path):
        from edge.drivers.base import SensorDriver

        driver = DHT22Driver(iio_path=tmp_path / "device0")
        assert isinstance(driver, SensorDriver)

    def test_driver_reading_shape(self, tmp_path):
        _make_device_dir(tmp_path / "device0", "dht11@11", "62600")
        driver = DHT22Driver(iio_path=tmp_path / "device0")
        reading = driver.read()

        assert hasattr(reading, "value")
        assert hasattr(reading, "unit")
        assert hasattr(reading, "ts")
        assert hasattr(reading, "healthy")
        assert isinstance(reading.as_dict(), dict)
        assert set(reading.as_dict().keys()) == {"value", "unit", "ts", "healthy"}
