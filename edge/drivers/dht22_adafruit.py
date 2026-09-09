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

This driver reads only humidity, consistent with the frozen six-channel
contract and mirroring edge/drivers/dht22.py's own discipline exactly --
DHT22's own on-chip temperature reading is never read or exposed as a
second `temperature` value; `temperature` remains DS18B20-only.
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


class DHT22AdafruitHumidityReader:
    """Reads %RH via adafruit_dht.DHT22. The underlying device object is
    created once (lazily, on first read) and reused across reads --
    matching Adafruit's own recommended usage and avoiding repeatedly
    re-acquiring the GPIO pin."""

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


def dht22_adafruit_raw_read(*, pin: int = _DEFAULT_PIN, use_pulseio: bool = False) -> RawRead:
    """Factory: create a RawRead callable from the Adafruit CircuitPython DHT22 driver."""
    reader = DHT22AdafruitHumidityReader(pin=pin, use_pulseio=use_pulseio)

    def _read() -> float:
        return reader.read_humidity_percent()

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
