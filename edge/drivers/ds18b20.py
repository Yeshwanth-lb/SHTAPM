"""Real DS18B20 waterproof temperature probe driver via 1-Wire (P1 · C1).

Reads temperature through the kernel `w1-gpio` + `w1-therm` 1-Wire drivers,
which expose each DS18B20 as a sysfs slave device — verified against a
physical DS18B20 probe on Raspberry Pi 5 (GPIO4, 4.7kΩ pull-up to 3.3V).
Requires the device-tree overlay `dtoverlay=w1-gpio,gpiopin=4` to be enabled
(config.txt); the strict 1-Wire timing happens in the kernel, not userspace
Python — same pattern as the DHT22 driver (edge/drivers/dht22.py).

Sysfs layout, e.g. for a probe with serial 00000055547c:
  /sys/bus/w1/devices/28-00000055547c/w1_slave

`w1_slave` content (two lines, kernel-formatted):
  4e 01 4b 46 7f ff 0c 10 5d : crc=5d YES
  4e 01 4b 46 7f ff 0c 10 5d t=27750

Line 1 ends "YES"/"NO" — the kernel's own CRC-8 check of the 9 scratchpad
bytes it read off the wire. Line 2's `t=<millidegrees>` is the temperature,
already CRC-validated and unit-converted by the kernel (divide by 1000 for
°C) — confirmed against a physical reading (t=27750 -> 27.75°C).

This driver reads only temperature, consistent with the frozen six-channel
contract — humidity is supplied separately by the DHT22 channel.
"""

from __future__ import annotations

import re
from pathlib import Path

from edge.drivers.base import RawRead, Sensor, SensorDriver

_W1_ROOT = Path("/sys/bus/w1/devices")
_FAMILY_PREFIX = "28-"  # DS18B20 1-Wire family code (0x28)
_SLAVE_FILE = "w1_slave"
_MILLIDEGREES_PER_DEGREE = 1000.0
_TEMP_PATTERN = re.compile(r"t=(-?\d+)")


def _find_w1_device(root: Path, family_prefix: str) -> Path:
    """Locate the 28-<serial> directory for a DS18B20 on the 1-Wire bus.

    The serial number is per-device (burned into the chip), so this scans
    for any directory matching the family-code prefix rather than assuming
    a fixed name. Returns the first match (sorted) — this driver assumes a
    single DS18B20 probe on the bus, consistent with the frozen one-probe
    temperature channel.
    """
    try:
        candidates = sorted(root.glob(f"{family_prefix}*"))
    except OSError as e:
        raise OSError(f"failed to list {root}: {e}") from e
    if not candidates:
        raise OSError(
            f"no 1-Wire device matching {family_prefix!r}* found under {root}; "
            "is dtoverlay=w1-gpio,gpiopin=<N> enabled in config.txt, and is the "
            "probe wired/pulled up correctly?"
        )
    return candidates[0]


class DS18B20TemperatureReader:
    """Reads °C from the kernel w1-therm driver's w1_slave file.

    Validates the kernel's own CRC check (line 1: "...YES"/"...NO") before
    trusting the parsed temperature (line 2: "t=<millidegrees>").
    """

    def __init__(
        self,
        *,
        device_path: str | Path | None = None,
        w1_root: str | Path = _W1_ROOT,
        family_prefix: str = _FAMILY_PREFIX,
    ) -> None:
        """Initialize the reader.

        Args:
            device_path: Explicit 28-<serial> directory (skips auto-discovery;
                mainly for tests / multi-probe setups).
            w1_root: Root to search for a DS18B20 device when device_path is
                not given. Default: /sys/bus/w1/devices (Pi 5).
            family_prefix: 1-Wire family-code directory prefix. Default: "28-"
                (DS18B20).
        """
        self._explicit_path = Path(device_path) if device_path is not None else None
        self._w1_root = Path(w1_root)
        self._family_prefix = family_prefix
        self._resolved_path: Path | None = None

    def _device_dir(self) -> Path:
        if self._explicit_path is not None:
            return self._explicit_path
        if self._resolved_path is None:
            self._resolved_path = _find_w1_device(self._w1_root, self._family_prefix)
        return self._resolved_path

    def read_temperature_c(self) -> float:
        """Read temperature (°C) from the w1_slave sysfs file.

        Raises OSError on any failure: device not found, sysfs read error,
        failed CRC ("...NO"), or malformed/missing temperature data.
        """
        device_dir = self._device_dir()
        slave_file = device_dir / _SLAVE_FILE
        try:
            raw_text = slave_file.read_text()
        except OSError as e:
            raise OSError(f"failed to read {slave_file}: {e}") from e

        lines = raw_text.strip().splitlines()
        if len(lines) < 2:
            raise OSError(f"malformed w1_slave content in {slave_file}: {raw_text!r}")

        if not lines[0].rstrip().endswith("YES"):
            raise OSError(f"CRC check failed reading {slave_file}: {lines[0]!r}")

        match = _TEMP_PATTERN.search(lines[1])
        if match is None:
            raise OSError(f"no temperature reading found in {slave_file}: {lines[1]!r}")
        try:
            millidegrees = int(match.group(1))
        except ValueError as e:
            raise OSError(f"unexpected temperature value in {slave_file}: {lines[1]!r}: {e}") from e

        return millidegrees / _MILLIDEGREES_PER_DEGREE


def ds18b20_raw_read(
    *,
    device_path: str | Path | None = None,
    w1_root: str | Path = _W1_ROOT,
    family_prefix: str = _FAMILY_PREFIX,
) -> RawRead:
    """Factory: create a RawRead callable from the DS18B20 (via kernel w1-therm).

    Args:
        device_path: Explicit 28-<serial> directory (skips auto-discovery).
        w1_root: Root to search when device_path is not given.
        family_prefix: 1-Wire family-code directory prefix.

    Returns a callable that reads °C from sysfs, or raises OSError on failure.
    """
    reader = DS18B20TemperatureReader(
        device_path=device_path, w1_root=w1_root, family_prefix=family_prefix
    )

    def _read() -> float:
        return reader.read_temperature_c()

    return _read


class DS18B20Driver(SensorDriver):
    """Real DS18B20 hardware driver conforming to SensorDriver interface.

    Reads temperature via the kernel w1-therm driver and wraps it in a
    Sensor (P1 base.py) for health handling. Never raises; unhealthy reads
    (missing device, failed CRC, malformed data, sysfs errors) return
    healthy=False, value=None (firmware discipline §02.8).
    """

    def __init__(
        self,
        *,
        device_path: str | Path | None = None,
        w1_root: str | Path = _W1_ROOT,
        family_prefix: str = _FAMILY_PREFIX,
    ) -> None:
        """Initialize the DS18B20 driver.

        Args:
            device_path: Explicit 28-<serial> directory (skips auto-discovery).
            w1_root: Root to search for the DS18B20 device. Default: Pi 5 sysfs.
            family_prefix: 1-Wire family-code directory prefix. Default: "28-".
        """
        self._sensor = Sensor(
            unit="°C",
            raw_read=ds18b20_raw_read(
                device_path=device_path, w1_root=w1_root, family_prefix=family_prefix
            ),
        )

    def read(self):
        """Read DS18B20 temperature (°C). Never raises; returns healthy=False on failure."""
        return self._sensor.read()
