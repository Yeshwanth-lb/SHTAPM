"""Real ADXL335 vibration sensor driver via MCP3008 SPI ADC (P1 · C1).

The ADXL335 is a 3-axis analog accelerometer with no digital interface of its
own; each axis (X/Y/Z) is wired to one MCP3008 ADC channel (SPI0 CE0), read
over the standard MCP3008 single-ended protocol via `spidev`.

Wiring (per config): X-OUT -> MCP3008 CH0, Y-OUT -> CH1, Z-OUT -> CH2,
VCC -> 3.3V, GND -> GND, MCP3008 on SPI0 CE0.

The frozen six-channel contract carries one scalar `vibration` (g) value,
but the ADXL335 exposes three raw axes — combining them requires a
sensitivity/zero-g/combination choice that isn't in the sensor bench-part
table (Doc PRD-4 §12.1) or the TRD. Per this project's documented discipline
of not inventing physics without data or a spec to point to (DECISIONS.md
D010/D013/D014/D017), this was raised with the user rather than assumed; the
approach below (magnitude of deviation from an at-rest baseline, g-converted
via the ADXL335's nominal datasheet sensitivity) was their explicit choice.

Conversion (approved, not per-chip calibrated):
  - MCP3008: 10-bit ADC (0-1023 counts), Vref = VCC = 3.3V.
  - ADXL335: nominal sensitivity 330 mV/g at Vs=3.3V (Analog Devices
    datasheet lists 300 mV/g @ Vs=3V, scaling proportionally with supply).
  - `ADXL335VibrationReader` captures each axis's raw ADC count as an
    at-rest baseline on the first successful read (absorbing each axis's
    fixed zero-g bias/orientation — including an axis that's wired but not
    yet moving, e.g. Y/Z on an unsoldered breadboard reading a constant,
    physically-arbitrary value: it simply contributes ~0 to the magnitude
    until it varies). Every read after that reports the Euclidean magnitude
    of the deviation from that baseline, in g. This is a *relative* (AC)
    vibration measure, not absolute tilt/orientation.

This driver reads only vibration, consistent with the frozen six-channel
contract — pressure and gas remain fake for now (also MCP3008 channels, on
a future BMP180/MQ-135 driver pass).
"""

from __future__ import annotations

import math

try:
    import spidev
except ImportError:
    spidev = None  # type: ignore

from edge.drivers.base import RawRead, Sensor, SensorDriver

_ADC_MAX_COUNT = 1023  # MCP3008: 10-bit, 0-1023
_ADC_COUNTS = _ADC_MAX_COUNT + 1  # 1024
_MCP3008_VREF_VOLTS = 3.3  # MCP3008 VDD/VREF tied to the same 3.3V rail as the ADXL335
_ADXL335_SENSITIVITY_V_PER_G = 0.330  # nominal @ Vs=3.3V; see module docstring
_VOLTS_PER_COUNT = _MCP3008_VREF_VOLTS / _ADC_COUNTS
_G_PER_COUNT = _VOLTS_PER_COUNT / _ADXL335_SENSITIVITY_V_PER_G


class ADXL335MCP3008Reader:
    """Reads raw 10-bit ADC counts (0-1023) for the X/Y/Z channels over SPI.

    Uses the standard MCP3008 single-ended read protocol: a 3-byte transfer
    `[start_bit, (8|channel)<<4, 0]` returns a 3-byte reply whose last 10 bits
    (low 2 bits of byte 1, all 8 bits of byte 2) are the ADC count.
    """

    def __init__(
        self,
        *,
        bus: int = 0,
        device: int = 0,
        max_speed_hz: int = 1_350_000,
        x_channel: int = 0,
        y_channel: int = 1,
        z_channel: int = 2,
    ) -> None:
        """Initialize the reader.

        Args:
            bus: SPI bus number. Default: 0 (SPI0).
            device: SPI chip-select device. Default: 0 (CE0).
            max_speed_hz: SPI clock speed. Default: 1.35 MHz (MCP3008 max at 3.3V
                is ~1.35 MHz per datasheet; safe default, not a measured value).
            x_channel: MCP3008 channel wired to ADXL335 X-OUT. Default: 0.
            y_channel: MCP3008 channel wired to ADXL335 Y-OUT. Default: 1.
            z_channel: MCP3008 channel wired to ADXL335 Z-OUT. Default: 2.
        """
        channels = (("x_channel", x_channel), ("y_channel", y_channel), ("z_channel", z_channel))
        for name, channel in channels:
            if not 0 <= channel <= 7:
                raise ValueError(f"{name}={channel!r} out of range; MCP3008 channels are 0-7")
        self._bus = bus
        self._device = device
        self._max_speed_hz = max_speed_hz
        self._x_channel = x_channel
        self._y_channel = y_channel
        self._z_channel = z_channel

    def _open_spi(self):
        """Open a fresh SpiDev handle. Called once per read; simplifies cleanup."""
        if spidev is None:
            raise ImportError("spidev not installed; install: pip install spidev")
        try:
            spi = spidev.SpiDev()
            spi.open(self._bus, self._device)
            spi.max_speed_hz = self._max_speed_hz
            spi.mode = 0
            return spi
        except Exception as e:
            raise OSError(f"failed to open SPI bus {self._bus}.{self._device}: {e}") from e

    @staticmethod
    def _read_channel(spi, channel: int) -> int:
        reply = spi.xfer2([1, (8 + channel) << 4, 0])
        value = ((reply[1] & 3) << 8) | reply[2]
        if not 0 <= value <= _ADC_MAX_COUNT:
            raise OSError(
                f"invalid MCP3008 reading on channel {channel}: {value} "
                f"(expected 0-{_ADC_MAX_COUNT})"
            )
        return value

    def read_raw_xyz(self) -> tuple[int, int, int]:
        """Read raw ADC counts (0-1023) for X, Y, Z.

        Raises OSError on any failure: SPI bus open failure, transfer error,
        or an out-of-range ADC reading.
        """
        spi = self._open_spi()
        try:
            x = self._read_channel(spi, self._x_channel)
            y = self._read_channel(spi, self._y_channel)
            z = self._read_channel(spi, self._z_channel)
        except OSError:
            raise
        except Exception as e:
            raise OSError(f"SPI read failed on bus {self._bus}.{self._device}: {e}") from e
        finally:
            try:
                spi.close()
            except Exception:
                pass
        return x, y, z


class ADXL335VibrationReader:
    """Combines raw X/Y/Z ADC reads into a single vibration-magnitude (g) scalar.

    See module docstring for the approved baseline + magnitude approach.
    """

    def __init__(
        self,
        *,
        bus: int = 0,
        device: int = 0,
        max_speed_hz: int = 1_350_000,
        x_channel: int = 0,
        y_channel: int = 1,
        z_channel: int = 2,
    ) -> None:
        self._reader = ADXL335MCP3008Reader(
            bus=bus,
            device=device,
            max_speed_hz=max_speed_hz,
            x_channel=x_channel,
            y_channel=y_channel,
            z_channel=z_channel,
        )
        self._baseline: tuple[int, int, int] | None = None

    def read_vibration_g(self) -> float:
        """Read vibration magnitude (g): Euclidean deviation from the at-rest
        baseline, captured on the first successful read (that first read
        returns 0.0 by definition — it establishes the baseline).

        Raises OSError on any read failure (propagated from
        ADXL335MCP3008Reader.read_raw_xyz).
        """
        x, y, z = self._reader.read_raw_xyz()
        if self._baseline is None:
            self._baseline = (x, y, z)
            return 0.0
        x0, y0, z0 = self._baseline
        dx, dy, dz = x - x0, y - y0, z - z0
        magnitude_counts = math.sqrt(dx * dx + dy * dy + dz * dz)
        return magnitude_counts * _G_PER_COUNT


def adxl335_raw_read(
    *,
    bus: int = 0,
    device: int = 0,
    max_speed_hz: int = 1_350_000,
    x_channel: int = 0,
    y_channel: int = 1,
    z_channel: int = 2,
) -> RawRead:
    """Factory: create a RawRead callable from the ADXL335 (via MCP3008/SPI).

    Returns a callable that reads vibration magnitude (g), or raises OSError
    on failure. See ADXL335VibrationReader for the baseline/magnitude approach.
    """
    reader = ADXL335VibrationReader(
        bus=bus,
        device=device,
        max_speed_hz=max_speed_hz,
        x_channel=x_channel,
        y_channel=y_channel,
        z_channel=z_channel,
    )

    def _read() -> float:
        return reader.read_vibration_g()

    return _read


class ADXL335Driver(SensorDriver):
    """Real ADXL335 hardware driver conforming to SensorDriver interface.

    Reads vibration magnitude (g) via MCP3008/SPI and wraps it in a Sensor
    (P1 base.py) for health handling. Never raises; unhealthy reads (SPI
    bus failure, transfer error, out-of-range ADC value) return
    healthy=False, value=None (firmware discipline §02.8).
    """

    def __init__(
        self,
        *,
        bus: int = 0,
        device: int = 0,
        max_speed_hz: int = 1_350_000,
        x_channel: int = 0,
        y_channel: int = 1,
        z_channel: int = 2,
    ) -> None:
        """Initialize the ADXL335 driver.

        Args:
            bus: SPI bus number. Default: 0 (SPI0).
            device: SPI chip-select device. Default: 0 (CE0).
            max_speed_hz: SPI clock speed. Default: 1.35 MHz.
            x_channel: MCP3008 channel wired to ADXL335 X-OUT. Default: 0.
            y_channel: MCP3008 channel wired to ADXL335 Y-OUT. Default: 1.
            z_channel: MCP3008 channel wired to ADXL335 Z-OUT. Default: 2.
        """
        self._sensor = Sensor(
            unit="g",
            raw_read=adxl335_raw_read(
                bus=bus,
                device=device,
                max_speed_hz=max_speed_hz,
                x_channel=x_channel,
                y_channel=y_channel,
                z_channel=z_channel,
            ),
        )

    def read(self):
        """Read ADXL335 vibration magnitude (g). Never raises; returns
        healthy=False on failure."""
        return self._sensor.read()
