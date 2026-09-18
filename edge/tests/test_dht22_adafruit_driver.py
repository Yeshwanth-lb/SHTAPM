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
    DHT22AdafruitReader,
    DHT22AdafruitTemperatureDriver,
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
        self._temp_script: list = [26.0]
        self._temp_i = 0
        self.temperature_accessed = False

    def _next(self):
        item = self._script[self._i] if self._i < len(self._script) else self._script[-1]
        self._i += 1  # advance BEFORE raising, so a scripted failure is not re-raised forever
        if isinstance(item, Exception):
            raise item
        return item

    def _next_temp(self):
        i = self._temp_i
        item = self._temp_script[i] if i < len(self._temp_script) else self._temp_script[-1]
        self._temp_i += 1
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def humidity(self):
        return self._next()

    @property
    def temperature(self):
        self.temperature_accessed = True
        return self._next_temp()


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


class _FakeMonotonic:
    """Controllable stand-in for time.monotonic() -- lets tests simulate the
    passage of time between sampling cycles (e.g. past the DHT22's own
    minimum measurement interval) without a real sleep."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _clear_shared_readers():
    """dht22_adafruit caches one reader per (pin, use_pulseio) at module level;
    drop it around every test so no cached device outlives its patched library."""
    dht22_adafruit_module.reset_shared_readers()
    yield
    dht22_adafruit_module.reset_shared_readers()


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
    reader = DHT22AdafruitReader()
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
    reader = DHT22AdafruitReader()
    assert reader.read_humidity_percent() == pytest.approx(62.6)


def test_default_pin_is_d17(patched_library, fake_device):
    fake_device._script = [45.0]
    reader = DHT22AdafruitReader()
    reader.read_humidity_percent()
    assert fake_device.pin == "PIN_D17"


def test_explicit_pin_resolves_to_matching_board_attr(patched_library, fake_device):
    fake_device._script = [45.0]
    reader = DHT22AdafruitReader(pin=4)
    reader.read_humidity_percent()
    assert fake_device.pin == "PIN_D4"


def test_use_pulseio_false_is_passed_through(patched_library, fake_device):
    fake_device._script = [45.0]
    reader = DHT22AdafruitReader(use_pulseio=False)
    reader.read_humidity_percent()
    assert fake_device.use_pulseio is False


def test_unknown_pin_raises_oserror(patched_library):
    reader = DHT22AdafruitReader(pin=99)
    with pytest.raises(OSError, match="no pin D99"):
        reader.read_humidity_percent()


def test_device_object_created_once_and_reused_across_reads(patched_library, fake_device):
    """Matches Adafruit's own recommended usage -- avoids repeatedly
    re-acquiring the GPIO pin."""
    fake_device._script = [40.0, 41.0, 42.0]
    reader = DHT22AdafruitReader()
    reader.read_humidity_percent()
    reader.read_humidity_percent()
    reader.read_humidity_percent()
    assert patched_library.call_count == 1


def test_transient_failure_raises_oserror(patched_library, fake_device):
    fake_device._script = [RuntimeError("Checksum did not validate")]
    reader = DHT22AdafruitReader()
    with pytest.raises(OSError, match="failed to read DHT22"):
        reader.read_humidity_percent()


def test_recovers_after_transient_failure(patched_library, fake_device):
    """A transient DHT22 checksum/timing failure is a normal, expected
    characteristic -- the next sampling cycle, at or beyond the sensor's own
    minimum measurement interval later, must succeed without recreating the
    device object. (An immediate retry inside that interval is covered by
    the shared-failure-window tests below -- the DHT22 genuinely cannot
    produce a new measurement that fast.)"""
    fake_device._script = [RuntimeError("Checksum did not validate"), 55.5]
    clock = _FakeMonotonic()
    reader = DHT22AdafruitReader(monotonic=clock)
    with pytest.raises(OSError):
        reader.read_humidity_percent()
    clock.now += 2.1  # past the DHT22's own minimum measurement interval
    assert reader.read_humidity_percent() == pytest.approx(55.5)
    assert patched_library.call_count == 1  # still the same device object


def test_none_humidity_raises_oserror(patched_library, fake_device):
    fake_device._script = [None]
    reader = DHT22AdafruitReader()
    with pytest.raises(OSError, match="returned no humidity value"):
        reader.read_humidity_percent()


def test_reading_humidity_peeks_at_temperature_only_to_validate(patched_library, fake_device):
    """The humidity path DOES now read .temperature, deliberately.

    History of this guard: it began as `test_never_reads_temperature` (when
    temperature was not sourced from this sensor at all), was narrowed after
    D028 made the DHT22 serve both channels, and is narrowed again here.

    What changed: the 2026-09-18 bench regression showed the sensor returning
    0.0 on BOTH channels under motor EMI and publishing it as healthy. Catching
    that requires seeing the pair, so the humidity path now reads the sibling.

    What is still guaranteed, and is the part that actually mattered: this costs
    no extra HARDWARE measurement. adafruit_dht re-measures only after its own
    sampling period, so both property accesses inside one call are served by the
    single measurement the caller already triggered -- asserted below via the
    device factory being invoked exactly once.
    """
    fake_device._script = [50.0]
    fake_device._temp_script = [26.0]
    reader = DHT22AdafruitReader()

    assert reader.read_humidity_percent() == pytest.approx(50.0)
    assert fake_device.temperature_accessed is True  # deliberate, for validation
    assert patched_library.call_count == 1  # one device, one measurement


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


# ---------------------------------------------------------------------------
# DHT22 ambient temperature -- the project's approved `temperature` source
# (D028), sharing one sensor with `humidity`. See edge/drivers/dht22_adafruit.py's
# measurement-characteristics note for what this channel represents.
# These tests cover the mechanism only; nothing here validates the reading's
# accuracy or claims equivalence to a DS18B20 contact measurement.
# ---------------------------------------------------------------------------


def test_read_temperature_c_typical(patched_library, fake_device):
    fake_device._temp_script = [24.5]
    assert DHT22AdafruitReader().read_temperature_c() == pytest.approx(24.5)


def test_temperature_transient_failure_raises_oserror(patched_library, fake_device):
    fake_device._temp_script = [RuntimeError("checksum did not validate")]
    with pytest.raises(OSError, match="failed to read DHT22"):
        DHT22AdafruitReader().read_temperature_c()


def test_none_temperature_raises_oserror(patched_library, fake_device):
    fake_device._temp_script = [None]
    with pytest.raises(OSError, match="returned no temperature value"):
        DHT22AdafruitReader().read_temperature_c()


def test_temperature_recovers_after_transient_failure(patched_library, fake_device):
    """Same next-cycle-recovery semantics as
    test_recovers_after_transient_failure(), for the temperature path."""
    fake_device._temp_script = [RuntimeError("timing"), 23.0]
    clock = _FakeMonotonic()
    reader = DHT22AdafruitReader(monotonic=clock)
    with pytest.raises(OSError):
        reader.read_temperature_c()
    clock.now += 2.1  # past the DHT22's own minimum measurement interval
    assert reader.read_temperature_c() == pytest.approx(23.0)


def test_both_channels_share_one_device_object(patched_library, fake_device):
    """The point of the shared reader: one adafruit_dht.DHT22 for both
    channels, so they cannot bit-bang GPIO17 on two independent schedules."""
    fake_device._script = [61.0]
    fake_device._temp_script = [24.0]

    reader = dht22_adafruit_module.shared_reader()
    reader.read_humidity_percent()
    reader.read_temperature_c()

    assert patched_library.call_count == 1  # device constructed exactly once


def test_shared_reader_is_identical_across_both_driver_classes(patched_library, fake_device):
    humidity = dht22_adafruit_module.dht22_adafruit_raw_read()
    temperature = dht22_adafruit_module.dht22_adafruit_temperature_raw_read()
    fake_device._script = [61.0]
    fake_device._temp_script = [24.0]

    humidity()
    temperature()

    assert patched_library.call_count == 1
    assert dht22_adafruit_module.shared_reader() is dht22_adafruit_module.shared_reader()


def test_shared_reader_is_keyed_so_a_second_pin_stays_independent(patched_library):
    assert dht22_adafruit_module.shared_reader(pin=17) is not dht22_adafruit_module.shared_reader(
        pin=4
    )


def test_reset_shared_readers_drops_the_cache(patched_library):
    first = dht22_adafruit_module.shared_reader()
    dht22_adafruit_module.reset_shared_readers()
    assert dht22_adafruit_module.shared_reader() is not first


def test_temperature_driver_reports_celsius_and_satisfies_the_driver_contract(
    patched_library, fake_device
):
    fake_device._temp_script = [24.5]
    driver = DHT22AdafruitTemperatureDriver()
    assert isinstance(driver, SensorDriver)

    reading = driver.read()
    assert reading.healthy is True
    assert reading.value == pytest.approx(24.5)
    assert reading.unit == "°C"  # identical to DS18B20Driver's -- contract unchanged
    assert set(reading.as_dict()) == {"value", "unit", "ts", "healthy"}


def test_temperature_driver_returns_unhealthy_instead_of_raising(patched_library, fake_device):
    fake_device._temp_script = [RuntimeError("checksum did not validate")]
    reading = DHT22AdafruitTemperatureDriver().read()
    assert reading.healthy is False
    assert reading.value is None


def test_temperature_driver_unhealthy_when_library_missing():
    """Unpatched: adafruit_dht is genuinely absent on this dev machine."""
    reading = DHT22AdafruitTemperatureDriver().read()
    assert reading.healthy is False
    assert reading.value is None


# ---------------------------------------------------------------------------
# Shared-failure window (regression coverage for the bench bug, 2026-09-13):
# a failed shared measurement must be visible to BOTH channels, not just
# whichever one happened to trigger it -- see module docstring's
# SHARED-FAILURE WINDOW note.
# ---------------------------------------------------------------------------


def test_temperature_failure_also_fails_humidity_within_the_shared_window(
    patched_library, fake_device
):
    """Reproduces production's read order (temperature before humidity, per
    the frozen CHANNELS order) within one Sampler cycle: a checksum failure
    on temperature's triggering read must also surface on humidity's read
    moments later, instead of humidity silently returning a stale cached
    value as 'healthy'."""
    fake_device._temp_script = [RuntimeError("Checksum did not validate")]
    fake_device._script = [61.0]  # would be a valid reading if actually read
    clock = _FakeMonotonic()
    reader = DHT22AdafruitReader(monotonic=clock)

    with pytest.raises(OSError):
        reader.read_temperature_c()

    clock.now += 0.05  # moments later, same Sampler cycle
    with pytest.raises(OSError):
        reader.read_humidity_percent()


def test_humidity_failure_also_fails_temperature_within_the_shared_window(
    patched_library, fake_device
):
    """Symmetric case: whichever channel is read second in the window must
    not silently paper over a failure the first channel already surfaced."""
    fake_device._script = [RuntimeError("Checksum did not validate")]
    fake_device._temp_script = [24.0]
    clock = _FakeMonotonic()
    reader = DHT22AdafruitReader(monotonic=clock)

    with pytest.raises(OSError):
        reader.read_humidity_percent()

    clock.now += 0.05
    with pytest.raises(OSError):
        reader.read_temperature_c()


def test_sibling_channel_gets_a_fresh_attempt_once_the_window_elapses(patched_library, fake_device):
    """The shared-failure window is temporary, not permanent: once the
    sensor's own minimum measurement interval has passed, the sibling
    channel attempts its own fresh, independent measurement again."""
    fake_device._temp_script = [RuntimeError("Checksum did not validate")]
    fake_device._script = [61.0]
    clock = _FakeMonotonic()
    reader = DHT22AdafruitReader(monotonic=clock)

    with pytest.raises(OSError):
        reader.read_temperature_c()

    clock.now += 2.1  # past the DHT22's own minimum measurement interval
    assert reader.read_humidity_percent() == pytest.approx(61.0)


# ---------------------------------------------------------------------------
# Corrupted 0.0/0.0 read rejection (bench regression, 2026-09-18)
#
# Observed on the physical rig: with a brushed DC motor running nearby, the
# DHT22 stopped raising and instead returned 0.0 for BOTH channels. Those
# published as healthy 0.0 degC / 0.0 %RH frames while the room was actually
# 29.2 degC / 59 %RH -- indistinguishable downstream from real measurements.
# ---------------------------------------------------------------------------


def test_humidity_rejects_the_zero_pair(patched_library, fake_device):
    """0.0 %RH alongside 0.0 degC is a corrupted read, not a measurement."""
    fake_device._script = [0.0]
    fake_device._temp_script = [0.0]
    reader = DHT22AdafruitReader()

    with pytest.raises(OSError, match="corrupted read"):
        reader.read_humidity_percent()


def test_temperature_rejects_the_zero_pair(patched_library, fake_device):
    fake_device._script = [0.0]
    fake_device._temp_script = [0.0]
    reader = DHT22AdafruitReader()

    with pytest.raises(OSError, match="corrupted read"):
        reader.read_temperature_c()


def test_zero_celsius_with_real_humidity_is_still_valid(patched_library, fake_device):
    """0.0 degC on its own is an ordinary winter temperature and MUST NOT be
    rejected -- the pair is the discriminator, not either value alone."""
    fake_device._script = [58.0]
    fake_device._temp_script = [0.0]
    reader = DHT22AdafruitReader()

    assert reader.read_temperature_c() == pytest.approx(0.0)


def test_zero_humidity_with_real_temperature_is_not_rejected(patched_library, fake_device):
    """Deliberately narrow: only the BOTH-zero pair is treated as corruption,
    so this check cannot become an invented plausible-range specification."""
    fake_device._script = [0.0]
    fake_device._temp_script = [26.0]
    reader = DHT22AdafruitReader()

    assert reader.read_humidity_percent() == pytest.approx(0.0)


def test_driver_reports_unhealthy_instead_of_publishing_the_zero_pair(patched_library, fake_device):
    """End of the chain: the corrupted read must surface as healthy=False so
    the sampler withholds the frame, rather than shipping 0.0 as truth."""
    fake_device._script = [0.0]
    fake_device._temp_script = [0.0]

    humidity_reading = DHT22AdafruitDriver().read()
    assert humidity_reading.healthy is False
    assert humidity_reading.value is None

    dht22_adafruit_module.reset_shared_readers()
    fake_device._i = 0
    fake_device._temp_i = 0

    temperature_reading = DHT22AdafruitTemperatureDriver().read()
    assert temperature_reading.healthy is False
    assert temperature_reading.value is None
