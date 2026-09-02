"""Real DHT22 humidity sensor driver via the Linux kernel IIO interface (P1 · C1).

Reads relative humidity through the kernel `dht11` staging driver, which is
protocol-compatible with DHT11/DHT22/AM2302 (sensor model auto-detected from
the wire checksum) — verified against a physical DHT22 on Raspberry Pi 5.
Requires the device-tree overlay `dtoverlay=dht11,gpiopin=<N>` to be enabled
(config.txt) so the sensor is exposed as a sysfs IIO device; the strict
microsecond bit-banging happens in the kernel, not in userspace Python, which
is what makes this reliable on Pi 5 (unlike userspace pulseio-based libraries).

Sysfs layout (per device), e.g. for gpiopin=17:
  /sys/bus/iio/devices/iio:deviceN/name                       -> "dht11" or "dht11@<gpio>"
  /sys/bus/iio/devices/iio:deviceN/in_humidityrelative_input  -> integer, milli-percent %RH
  /sys/bus/iio/devices/iio:deviceN/in_temp_input               -> integer, milli-°C (unused here)

The kernel's `name` attribute is `pdev->name` — on Raspberry Pi OS this is the
overlay-instantiated platform device name, observed as `dht11@11` (a
`<driver>@<instance>` form, not the bare driver name `dht11`), so discovery
matches on the `dht11` prefix rather than exact equality (verified against a
physical DHT22 on Raspberry Pi 5).

`in_humidityrelative_input` / `in_temp_input` follow the standard IIO ABI
(Documentation/ABI/testing/sysfs-bus-iio): values are in milli-percent /
milli-degrees Celsius, i.e. divide by 1000 (e.g. 62600 -> 62.6 %RH) — verified
against the kernel driver's dht11_decode(), which stores the sensor's native
0.1%-resolution count ×100 (626 ×100 = 62600), and against physical readings.

This driver reads only humidity, consistent with the frozen six-channel
contract — temperature is supplied separately by the DS18B20 channel.
"""

from __future__ import annotations

from pathlib import Path

from edge.drivers.base import RawRead, Sensor, SensorDriver

_IIO_ROOT = Path("/sys/bus/iio/devices")
_DRIVER_NAME = "dht11"  # kernel platform-device name prefix; handles DHT11/DHT22/AM2302 alike
_HUMIDITY_ATTR = "in_humidityrelative_input"
_MILLI_PERCENT_PER_PERCENT = 1000.0


def _matches_driver(name: str, driver_name: str) -> bool:
    """True if `name` is the bare driver name or a `<driver>@<instance>` variant.

    The kernel's IIO `name` attribute is the platform device name (`pdev->name`),
    which on Raspberry Pi OS's dht11 overlay is instantiated as `dht11@<gpio>`
    (e.g. `dht11@11`) rather than the bare `dht11` — both forms are accepted.
    """
    return name == driver_name or name.startswith(f"{driver_name}@")


def _find_iio_device(root: Path, driver_name: str) -> Path:
    """Locate the iio:deviceN directory for the dht11 kernel driver.

    The device index isn't fixed (depends on overlay load order / other IIO
    devices present), so this scans each device's `name` file rather than
    assuming iio:device0.
    """
    try:
        candidates = sorted(root.glob("iio:device*"))
    except OSError as e:
        raise OSError(f"failed to list {root}: {e}")
    for candidate in candidates:
        try:
            name = (candidate / "name").read_text().strip()
        except OSError:
            continue
        if _matches_driver(name, driver_name):
            return candidate
    raise OSError(
        f"no IIO device matching driver {driver_name!r} (or {driver_name}@*) "
        f"found under {root}; is dtoverlay=dht11,gpiopin=<N> enabled in config.txt?"
    )


class DHT22HumidityReader:
    """Reads %RH from the kernel dht11 IIO driver's in_humidityrelative_input.

    The kernel reports the value in milli-percent per the standard IIO ABI
    (divide by 1000, e.g. 62600 → 62.6 %RH).
    """

    def __init__(
        self,
        *,
        iio_path: str | Path | None = None,
        iio_root: str | Path = _IIO_ROOT,
    ) -> None:
        """Initialize the reader.

        Args:
            iio_path: Explicit iio:deviceN directory (skips auto-discovery;
                mainly for tests / non-default overlay setups).
            iio_root: Root to search for the dht11 device when iio_path is
                not given. Default: /sys/bus/iio/devices (Pi 5).
        """
        self._explicit_path = Path(iio_path) if iio_path is not None else None
        self._iio_root = Path(iio_root)
        self._resolved_path: Path | None = None

    def _device_dir(self) -> Path:
        if self._explicit_path is not None:
            return self._explicit_path
        if self._resolved_path is None:
            self._resolved_path = _find_iio_device(self._iio_root, _DRIVER_NAME)
        return self._resolved_path

    def read_humidity_percent(self) -> float:
        """Read relative humidity (%RH) from sysfs.

        Raises OSError on any failure (device not found, sysfs read error,
        driver returned malformed/non-numeric data).
        """
        device_dir = self._device_dir()
        raw_file = device_dir / _HUMIDITY_ATTR
        try:
            raw_text = raw_file.read_text().strip()
        except OSError as e:
            raise OSError(f"failed to read {raw_file}: {e}")
        try:
            raw_value = int(raw_text)
        except ValueError as e:
            raise OSError(f"unexpected value {raw_text!r} in {raw_file}: {e}")
        return raw_value / _MILLI_PERCENT_PER_PERCENT


def dht22_raw_read(
    *,
    iio_path: str | Path | None = None,
    iio_root: str | Path = _IIO_ROOT,
) -> RawRead:
    """Factory: create a RawRead callable from the DHT22 (via kernel dht11 driver).

    Args:
        iio_path: Explicit iio:deviceN directory (skips auto-discovery).
        iio_root: Root to search when iio_path is not given.

    Returns a callable that reads %RH from sysfs, or raises OSError on failure.
    """
    reader = DHT22HumidityReader(iio_path=iio_path, iio_root=iio_root)

    def _read() -> float:
        return reader.read_humidity_percent()

    return _read


class DHT22Driver(SensorDriver):
    """Real DHT22 hardware driver conforming to SensorDriver interface.

    Reads relative humidity via the kernel dht11 IIO driver and wraps it in a
    Sensor (P1 base.py) for health handling. Never raises; unhealthy reads
    return healthy=False, value=None (firmware discipline §02.8).
    """

    def __init__(
        self,
        *,
        iio_path: str | Path | None = None,
        iio_root: str | Path = _IIO_ROOT,
    ) -> None:
        """Initialize the DHT22 driver.

        Args:
            iio_path: Explicit iio:deviceN directory (skips auto-discovery).
            iio_root: Root to search for the dht11 device. Default: Pi 5 sysfs.
        """
        self._sensor = Sensor(
            unit="%",
            raw_read=dht22_raw_read(iio_path=iio_path, iio_root=iio_root),
        )

    def read(self):
        """Read DHT22 humidity (%). Never raises; returns healthy=False on failure."""
        return self._sensor.read()
