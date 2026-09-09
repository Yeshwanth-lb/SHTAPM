"""Real DHT22 humidity sensor driver via the Adafruit CircuitPython DHT
library (P1 · C1) -- an ALTERNATE integration to the kernel-IIO
edge/drivers/dht22.py, not a replacement of it. That file is left fully
untouched; both driver classes remain available, only one is registered
as "the" real humidity driver at a time (see edge/drivers/registry.py).

Chosen because a working standalone Adafruit CircuitPython DHT22 test was
already validated on this bench's GPIO17 wiring, without confirming the
kernel dtoverlay=dht11,gpiopin=<N> overlay edge/drivers/dht22.py needs.
See that module's own docstring for why kernel IIO was originally chosen
(userspace bit-banging is documented there as LESS reliable on Pi 5) --
this driver is the pragmatic alternative for the bench configuration
that is actually working right now, not a claim that it supersedes the
kernel-IIO approach's reliability.

use_pulseio=False (the caller-specified, already-validated configuration)
avoids the pulseio C-extension path entirely, using adafruit_dht's plain-
Python bit-bang timing instead.

TEMPORARY DUAL-CHANNEL USE (temperature + humidity) -- deliberate,
operator-approved deviation from PRD 12.1, see the DHT22-ambient-
temperature record in project-state/DECISIONS.md before relying on any
data produced in this configuration:

DHT22 exposes an on-chip temperature reading alongside humidity. The DS18B20
(edge/drivers/ds18b20.py) is this project's canonical `temperature` source
and remains registered as such (edge/drivers/registry.py's
_REAL_DRIVER_CLASSES is unchanged); it is currently undetected on the bench,
so DHT22AdafruitTemperatureDriver below is offered as an explicitly-named
SUBSTITUTE -- never as `kind="real"`, never selected implicitly, and never
as a fallback the registry picks on its own.

What DHT22 measures here is AMBIENT AIR TEMPERATURE at the sensor. It is
NOT the motor/bearing temperature PRD 12.1 specifies for this channel
("Direct", DS18B20), and it is NOT interchangeable with a DS18B20 reading:
different physical quantity, different placement, different failure mode.
PRD 12.1's design-integrity note additionally keeps temperature and humidity
on separate parts so the trust engine's cross-sensor correlation term is not
defeated by two perfectly-correlated channels from one device -- sourcing
both here knowingly sets that property aside for the duration.

BOTH channels are served by ONE shared reader per (pin, use_pulseio) --
see shared_reader() below. Two independent adafruit_dht.DHT22 objects on
one GPIO would bit-bang the same pin on two schedules; one shared device
means one measurement serves both channels (adafruit_dht re-measures only
after its own 2s sampling period, so back-to-back .temperature/.humidity
access reuses a single measurement).
"""

from __future__ import annotations

try:
    import adafruit_dht
    import board
except ImportError:
    adafruit_dht = None  # type: ignore
    board = None  # type: ignore

from edge.drivers.base import RawRead, Sensor, SensorDriver

_DEFAULT_PIN = 17


class DHT22AdafruitReader:
    """Reads %RH and/or degC via one adafruit_dht.DHT22. The underlying
    device object is created once (lazily, on first read) and reused across
    reads -- matching Adafruit's own recommended usage and avoiding
    repeatedly re-acquiring the GPIO pin. One instance can serve both the
    humidity and temperature channels; see shared_reader()."""

    def __init__(self, *, pin: int = _DEFAULT_PIN, use_pulseio: bool = False) -> None:
        self._pin = pin
        self._use_pulseio = use_pulseio
        self._device: object | None = None

    def _ensure_device(self) -> object:
        if adafruit_dht is None or board is None:
            raise ImportError(
                "adafruit_dht/board not installed; install: pip install adafruit-circuitpython-dht"
            )
        if self._device is None:
            try:
                pin_obj = getattr(board, f"D{self._pin}")
            except AttributeError as e:
                raise OSError(f"board has no pin D{self._pin}") from e
            self._device = adafruit_dht.DHT22(pin_obj, use_pulseio=self._use_pulseio)
        return self._device

    def read_humidity_percent(self) -> float:
        """Read relative humidity (%RH).

        Raises OSError on any failure -- transient checksum/timing
        failures are a normal, expected DHT22 characteristic;
        Sensor.read()'s existing raise -> unhealthy handling already
        covers this, so no new retry logic is added here."""
        device = self._ensure_device()
        try:
            value = device.humidity
        except Exception as e:
            raise OSError(f"failed to read DHT22 (Adafruit, GPIO{self._pin}): {e}") from e
        if value is None:
            raise OSError(f"DHT22 (Adafruit, GPIO{self._pin}) returned no humidity value")
        return float(value)

    def read_temperature_c(self) -> float:
        """Read AMBIENT AIR temperature (°C) at the DHT22.

        NOT motor/bearing temperature -- see this module's docstring and
        the DECISIONS.md record it names. Same failure discipline as
        read_humidity_percent(): raises OSError, and Sensor.read() turns
        that into healthy=False without new retry logic.

        Reads the same device object as read_humidity_percent(); adafruit_dht
        re-measures only after its own 2s sampling period, so calling both
        within one 1Hz acquisition cycle costs one hardware measurement,
        not two."""
        device = self._ensure_device()
        try:
            value = device.temperature
        except Exception as e:
            raise OSError(f"failed to read DHT22 (Adafruit, GPIO{self._pin}): {e}") from e
        if value is None:
            raise OSError(f"DHT22 (Adafruit, GPIO{self._pin}) returned no temperature value")
        return float(value)


# One reader per physical (pin, use_pulseio) configuration. Both channel
# drivers below resolve through this, so temperature and humidity share a
# single adafruit_dht.DHT22 device rather than contending for the same GPIO
# with two independent bit-bang schedules. Keyed (not a bare singleton) so a
# second DHT22 on another pin stays independent.
_SHARED_READERS: dict[tuple[int, bool], DHT22AdafruitReader] = {}


def shared_reader(*, pin: int = _DEFAULT_PIN, use_pulseio: bool = False) -> DHT22AdafruitReader:
    """The one reader for this (pin, use_pulseio) -- created on first use."""
    key = (pin, use_pulseio)
    if key not in _SHARED_READERS:
        _SHARED_READERS[key] = DHT22AdafruitReader(pin=pin, use_pulseio=use_pulseio)
    return _SHARED_READERS[key]


def reset_shared_readers() -> None:
    """Drop every cached reader (and with it its cached device object).

    Test-isolation hook only -- nothing in the live path calls this. The
    live runtime builds its drivers once at startup and keeps them for the
    process's life (see edge/main.py)."""
    _SHARED_READERS.clear()


def dht22_adafruit_raw_read(*, pin: int = _DEFAULT_PIN, use_pulseio: bool = False) -> RawRead:
    """Factory: humidity (%RH) RawRead over the shared DHT22 reader."""
    reader = shared_reader(pin=pin, use_pulseio=use_pulseio)

    def _read() -> float:
        return reader.read_humidity_percent()

    return _read


def dht22_adafruit_temperature_raw_read(
    *, pin: int = _DEFAULT_PIN, use_pulseio: bool = False
) -> RawRead:
    """Factory: AMBIENT temperature (°C) RawRead over the shared DHT22
    reader -- the same device object dht22_adafruit_raw_read() uses."""
    reader = shared_reader(pin=pin, use_pulseio=use_pulseio)

    def _read() -> float:
        return reader.read_temperature_c()

    return _read


class DHT22AdafruitDriver(SensorDriver):
    """Real DHT22 hardware driver (Adafruit CircuitPython backend)
    conforming to SensorDriver -- same interface/output shape as
    edge/drivers/dht22.py's DHT22Driver (unit="%", Reading contract
    unchanged). Never raises; unhealthy reads return healthy=False,
    value=None (firmware discipline TRD §02.8)."""

    def __init__(self, *, pin: int = _DEFAULT_PIN, use_pulseio: bool = False) -> None:
        self._sensor = Sensor(
            unit="%",
            raw_read=dht22_adafruit_raw_read(pin=pin, use_pulseio=use_pulseio),
        )

    def read(self):
        """Read DHT22 humidity (%) via Adafruit CircuitPython. Never
        raises; returns healthy=False on failure."""
        return self._sensor.read()


class DHT22AdafruitTemperatureDriver(SensorDriver):
    """TEMPORARY SUBSTITUTE `temperature` driver: DHT22 ambient air temp.

    Registered as a SUBSTITUTE, never as this channel's real driver --
    DS18B20Driver remains registry._REAL_DRIVER_CLASSES["temperature"], so
    restoring it is removing this substitution, not a redesign. Selecting
    this driver is always an explicit act (DriverSpec(kind="substitute") or
    SHTAPM_DRIVER_TEMPERATURE=substitute); the registry never falls back to
    it on its own.

    Emits unit="°C" exactly as DS18B20Driver does, so the frozen
    six-channel contract, the wire frame, and every downstream consumer are
    untouched -- which is precisely why the physical-meaning caveat in this
    module's docstring cannot be read off the wire and must travel with the
    data. Never raises; unhealthy reads return healthy=False, value=None
    (firmware discipline TRD §02.8)."""

    def __init__(self, *, pin: int = _DEFAULT_PIN, use_pulseio: bool = False) -> None:
        self._sensor = Sensor(
            unit="°C",
            raw_read=dht22_adafruit_temperature_raw_read(pin=pin, use_pulseio=use_pulseio),
        )

    def read(self):
        """Read DHT22 ambient temperature (°C). Never raises; returns
        healthy=False on failure."""
        return self._sensor.read()
