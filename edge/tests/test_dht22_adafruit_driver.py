"""Real DHT22 driver tests (Adafruit CircuitPython backend, P1 · C1) --
hardware-free, mocking the module-level `adafruit_dht`/`board` globals
exactly like edge/tests/test_bmp280_driver.py mocks `smbus2` and
edge/tests/test_adxl335_driver.py mocks `spidev`. `adafruit_dht`/`board`
are not installed on this dev machine, so
edge.drivers.dht22_adafruit.adafruit_dht/board are already None at import
time -- the "library not installed" tests below exercise that real,
unmocked state directly.
"""

from __future__ import annotations

import pytest

import edge.drivers.dht22_adafruit as dht22_adafruit_module
from edge.drivers.base import SensorDriver
from edge.drivers.dht22_adafruit import (
    DHT22AdafruitDriver,
    DHT22AdafruitHumidityReader,
    dht22_adafruit_raw_read,
)


class _FakeBoard:
    D17 = "PIN_D17"
    D4 = "PIN_D4"


class _FakeDHT22Device:
    """Stand-in for adafruit_dht.DHT22 -- .humidity is a property whose
    behavior is scripted per test via a list of values/exceptions,
    mirroring edge/drivers/fake.py's scripted_raw() convention."""

    def __init__(self, pin, use_pulseio=False):
        self.pin = pin
        self.use_pulseio = use_pulseio
        self._script: list = []
        self._i = 0
        self.temperature_accessed = False

    def _next(self):
        item = self._script[self._i] if self._i < len(self._script) else self._script[-1]
        self._i += 1
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def humidity(self):
        return self._next()

    @property
    def temperature(self):  # pragma: no cover - must never be accessed
        self.temperature_accessed = True
        return 26.0


class _FakeAdafruitDHT:
    """Stand-in for the adafruit_dht module -- .DHT22 is the device factory."""

    def __init__(self, device: _FakeDHT22Device) -> None:
        self._device = device
        self.call_count = 0

    def DHT22(self, pin, use_pulseio=False):  # noqa: N802 (matches real library's class name)
        self.call_count += 1
        self._device.pin = pin
        self._device.use_pulseio = use_pulseio
        return self._device


@pytest.fixture()
def fake_device() -> _FakeDHT22Device:
    return _FakeDHT22Device(pin=None)


@pytest.fixture()
def patched_library(monkeypatch, fake_device):
    """Install the fake adafruit_dht/board modules for the duration of one test."""
    fake_module = _FakeAdafruitDHT(fake_device)
    monkeypatch.setattr(dht22_adafruit_module, "adafruit_dht", fake_module)
    monkeypatch.setattr(dht22_adafruit_module, "board", _FakeBoard)
    return fake_module


# ---------------------------------------------------------------------------
# Library-not-installed path (real, unmocked state on this dev machine)
# ---------------------------------------------------------------------------


def test_library_not_installed_on_this_dev_machine():
    """Sanity check for the tests below: confirms the try/except ImportError
    guard actually triggered (adafruit_dht/board genuinely aren't installed
    here), same guard that protects edge.drivers.registry from crashing on
    any machine without this Pi-only library."""
    assert dht22_adafruit_module.adafruit_dht is None
    assert dht22_adafruit_module.board is None


def test_reader_raises_import_error_when_library_missing():
    reader = DHT22AdafruitHumidityReader()
    with pytest.raises(ImportError, match="adafruit_dht/board not installed"):
        reader.read_humidity_percent()


def test_driver_read_returns_unhealthy_not_raise_when_library_missing():
    """Sensor.read()'s existing raise -> unhealthy handling covers ImportError
    exactly like any other raw_read failure -- never propagates."""
    driver = DHT22AdafruitDriver()
    reading = driver.read()
    assert reading.healthy is False
    assert reading.value is None
    assert reading.unit == "%"


# ---------------------------------------------------------------------------
# Mocked-library path
# ---------------------------------------------------------------------------


def test_read_humidity_percent_typical(patched_library, fake_device):
    fake_device._script = [62.6]
    reader = DHT22AdafruitHumidityReader()
    assert reader.read_humidity_percent() == pytest.approx(62.6)


def test_default_pin_is_d17(patched_library, fake_device):
    fake_device._script = [45.0]
    reader = DHT22AdafruitHumidityReader()
    reader.read_humidity_percent()
    assert fake_device.pin == "PIN_D17"


def test_explicit_pin_resolves_to_matching_board_attr(patched_library, fake_device):
    fake_device._script = [45.0]
    reader = DHT22AdafruitHumidityReader(pin=4)
    reader.read_humidity_percent()
    assert fake_device.pin == "PIN_D4"


def test_use_pulseio_false_is_passed_through(patched_library, fake_device):
    fake_device._script = [45.0]
    reader = DHT22AdafruitHumidityReader(use_pulseio=False)
    reader.read_humidity_percent()
    assert fake_device.use_pulseio is False


def test_unknown_pin_raises_oserror(patched_library):
    reader = DHT22AdafruitHumidityReader(pin=99)
    with pytest.raises(OSError, match="no pin D99"):
        reader.read_humidity_percent()


def test_device_object_created_once_and_reused_across_reads(patched_library, fake_device):
    """Matches Adafruit's own recommended usage -- avoids repeatedly
    re-acquiring the GPIO pin."""
    fake_device._script = [40.0, 41.0, 42.0]
    reader = DHT22AdafruitHumidityReader()
    reader.read_humidity_percent()
    reader.read_humidity_percent()
    reader.read_humidity_percent()
    assert patched_library.call_count == 1


def test_transient_failure_raises_oserror(patched_library, fake_device):
    fake_device._script = [RuntimeError("Checksum did not validate")]
    reader = DHT22AdafruitHumidityReader()
    with pytest.raises(OSError, match="failed to read DHT22"):
        reader.read_humidity_percent()


def test_recovers_after_transient_failure(patched_library, fake_device):
    """A transient DHT22 checksum/timing failure is a normal, expected
    characteristic -- the next read must succeed without recreating the
    device object."""
    fake_device._script = [RuntimeError("Checksum did not validate"), 55.5]
    reader = DHT22AdafruitHumidityReader()
    with pytest.raises(OSError):
        reader.read_humidity_percent()
    assert reader.read_humidity_percent() == pytest.approx(55.5)
    assert patched_library.call_count == 1  # still the same device object


def test_none_humidity_raises_oserror(patched_library, fake_device):
    fake_device._script = [None]
    reader = DHT22AdafruitHumidityReader()
    with pytest.raises(OSError, match="returned no humidity value"):
        reader.read_humidity_percent()


def test_never_reads_temperature(patched_library, fake_device):
    """Structural guard: mirrors edge/drivers/dht22.py's own discipline --
    temperature stays DS18B20-only, never sourced from this sensor."""
    fake_device._script = [50.0]
    reader = DHT22AdafruitHumidityReader()
    reader.read_humidity_percent()
    assert fake_device.temperature_accessed is False


# ---------------------------------------------------------------------------
# dht22_adafruit_raw_read factory
# ---------------------------------------------------------------------------


def test_raw_read_returns_callable(patched_library, fake_device):
    fake_device._script = [50.0]
    raw_read = dht22_adafruit_raw_read()
    assert callable(raw_read)
    assert raw_read() == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# DHT22AdafruitDriver -- full SensorDriver implementation
# ---------------------------------------------------------------------------


def test_driver_read_healthy(patched_library, fake_device):
    fake_device._script = [62.6]
    driver = DHT22AdafruitDriver()
    reading = driver.read()

    assert reading.healthy is True
    assert reading.value == pytest.approx(62.6)
    assert reading.unit == "%"
    assert reading.ts is not None


def test_driver_read_failure_returns_unhealthy_not_raise(patched_library, fake_device):
    fake_device._script = [RuntimeError("blip")]
    driver = DHT22AdafruitDriver()
    reading = driver.read()

    assert reading.healthy is False
    assert reading.value is None
    assert reading.unit == "%"


def test_driver_implements_sensor_driver():
    driver = DHT22AdafruitDriver()
    assert isinstance(driver, SensorDriver)


def test_driver_reading_shape(patched_library, fake_device):
    fake_device._script = [62.6]
    driver = DHT22AdafruitDriver()
    reading = driver.read()

    assert hasattr(reading, "value")
    assert hasattr(reading, "unit")
    assert hasattr(reading, "ts")
    assert hasattr(reading, "healthy")
    assert isinstance(reading.as_dict(), dict)
    assert set(reading.as_dict().keys()) == {"value", "unit", "ts", "healthy"}


def test_driver_matches_kernel_driver_unit_and_shape():
    """Same output format as edge/drivers/dht22.py's DHT22Driver -- unit="%",
    identical Reading contract -- confirmed by import, not duplicated logic."""
    from edge.drivers.dht22 import DHT22Driver

    # Both construct a Sensor with unit="%" -- verified structurally via a
    # library-missing read (no hardware needed for either on this machine).
    adafruit_driver = DHT22AdafruitDriver()
    kernel_driver = DHT22Driver(iio_path="/nonexistent")
    assert adafruit_driver.read().unit == kernel_driver.read().unit == "%"
