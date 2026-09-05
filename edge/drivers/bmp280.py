"""Real BMP280 pressure sensor driver over I²C (P1 · C1).

BMP280 replaces the documented BMP180 for the `pressure` channel
(`project-state/DECISIONS.md` D027) — same atmospheric-pressure-proxy
semantics as BMP180 (D010/D014): reads ambient atmospheric pressure, NOT
water-line/discharge pressure. The frozen `pressure` channel and its unit
("hPa") are unchanged; this driver does not add a channel, and does not
expose BMP280's on-chip temperature reading as a second `temperature` value
— `temperature` remains DS18B20-only, kept independent of any other channel
per the PRD's own design-integrity note (§12, cross-sensor correlation must
not be silently defeated by two channels sourced from one part). BMP280's
temperature is read only internally, as required by its own pressure
compensation formula (`t_fine`).

Hardware-validated on this Pi (I²C bus 1, address 0x76; chip ID 0x58
confirmed via `edge/scripts/bmp280_hwtest.py`, live readings ~29-30.6°C /
~913.8-914.0 hPa). Register map / compensation formulas are the Bosch
BMP280 datasheet's 64-bit-integer reference version — reused verbatim from
the bench-validated `bmp280_hwtest.py`, not re-derived here.

Read strategy: exclusively `read_i2c_block_data()` (calibration block, chip
ID, measurement data) — never `read_byte_data()`. This is evidence-based,
not a style preference: on this board, single-byte SMBus reads
intermittently returned "Remote I/O error" while block reads (matching
`i2cdump`'s own read style) succeeded consistently across the hardware
bring-up. See `bmp280_hwtest.py`'s module docstring for the original
diagnosis.

BMP280 register map:
  0x88-0x9F: calibration coefficients (dig_T1-3, dig_P1-9), read once and
    cached — factory-programmed, does not change between reads.
  0xD0: chip ID (0x58 for BMP280) — verified once, alongside calibration.
  0xF3: status (bit 3 = measuring)
  0xF4: ctrl_meas (osrs_t/osrs_p/mode) — forced mode triggers one conversion
    then returns to sleep, matching this driver's poll-then-read-once shape.
  0xF5: config (standby/filter/spi3w_en)
  0xF7-0xFC: press_msb..temp_xlsb (20-bit raw ADC counts each)
"""

from __future__ import annotations

import struct
import time

try:
    import smbus2
except ImportError:
    smbus2 = None  # type: ignore

from edge.drivers.base import RawRead, Sensor, SensorDriver

_REG_CALIB_START = 0x88
_CALIB_LENGTH = 24  # dig_T1..T3, dig_P1..P9 — 12 fields x 2 bytes

_REG_CHIP_ID = 0xD0
_EXPECTED_CHIP_ID = 0x58

_REG_CTRL_MEAS = 0xF4
_REG_CONFIG = 0xF5
_REG_STATUS = 0xF3
_STATUS_MEASURING_BIT = 0x08

_REG_DATA_START = 0xF7  # press_msb, press_lsb, press_xlsb, temp_msb, temp_lsb, temp_xlsb
_DATA_LENGTH = 6

# ctrl_meas: osrs_t=001 (x1), osrs_p=001 (x1), mode=01 (forced) -> 0b001_001_01
_CTRL_MEAS_FORCED_OSRS_X1 = 0x25
# config: t_sb=000 (irrelevant in forced mode), filter=000 (off), spi3w_en=0 (I2C)
_CONFIG_NO_FILTER_I2C = 0x00

_MEASUREMENT_TIMEOUT_S = 0.1  # generous margin over osrs_t=1/osrs_p=1's few-ms datasheet typical
_MEASUREMENT_POLL_INTERVAL_S = 0.005


class BMP280Calibration:
    """Parsed calibration coefficients (dig_T1..T3, dig_P1..P9)."""

    def __init__(self, raw: bytes) -> None:
        (
            self.dig_T1, self.dig_T2, self.dig_T3,
            self.dig_P1, self.dig_P2, self.dig_P3, self.dig_P4,
            self.dig_P5, self.dig_P6, self.dig_P7, self.dig_P8, self.dig_P9,
        ) = struct.unpack("<HhhHhhhhhhhh", raw)


def _compensate_temperature(adc_T: int, cal: BMP280Calibration) -> tuple[float, int]:
    """Bosch BMP280 datasheet, 64-bit integer compensation formula.
    Returns (temperature_degC, t_fine) — t_fine feeds pressure compensation."""
    var1 = (((adc_T >> 3) - (cal.dig_T1 << 1)) * cal.dig_T2) >> 11
    var2 = (((((adc_T >> 4) - cal.dig_T1) * ((adc_T >> 4) - cal.dig_T1)) >> 12) * cal.dig_T3) >> 14
    t_fine = var1 + var2
    temperature_c = ((t_fine * 5 + 128) >> 8) / 100.0
    return temperature_c, t_fine


def _compensate_pressure(adc_P: int, t_fine: int, cal: BMP280Calibration) -> float:
    """Bosch BMP280 datasheet, 64-bit integer compensation formula.
    Returns pressure in Pa (divide by 100 for hPa). Raises OSError if the
    dig_P1 compensation term is zero (would otherwise divide by zero)."""
    var1 = t_fine - 128000
    var2 = var1 * var1 * cal.dig_P6
    var2 = var2 + ((var1 * cal.dig_P5) << 17)
    var2 = var2 + (cal.dig_P4 << 35)
    var1 = ((var1 * var1 * cal.dig_P3) >> 8) + ((var1 * cal.dig_P2) << 12)
    var1 = (((1 << 47) + var1) * cal.dig_P1) >> 33
    if var1 == 0:
        raise OSError("BMP280 pressure compensation: dig_P1 term is zero (division by zero)")
    p = 1048576 - adc_P
    p = (((p << 31) - var2) * 3125) // var1
    var1 = (cal.dig_P9 * (p >> 13) * (p >> 13)) >> 25
    var2 = (cal.dig_P8 * p) >> 19
    p = ((p + var1 + var2) >> 8) + (cal.dig_P7 << 4)
    return p / 256.0


class BMP280Reader:
    """Encapsulates BMP280 I²C register access, calibration/chip-ID caching,
    forced-mode measurement, and pressure compensation.

    Uses `read_i2c_block_data()` exclusively (never `read_byte_data()`) —
    see module docstring for why. Chip ID and calibration coefficients are
    read once and cached (both are static/factory-programmed); every read
    triggers a fresh forced-mode conversion.
    """

    def __init__(self, bus_num: int = 1, address: int = 0x76):
        """Initialize the I²C bus number and BMP280 address.

        Args:
            bus_num: I²C bus number (e.g. 1 for /dev/i2c-1). Default: 1 (Pi 5).
            address: BMP280 7-bit address. Default: 0x76 (confirmed on this
                board; the alternate is 0x77 depending on the SDO pin strap).
        """
        self._bus_num = bus_num
        self._address = address
        self._calibration: BMP280Calibration | None = None

    def _open_bus(self) -> object:
        """Lazy-open I²C bus (smbus2). Called once per read; simplifies cleanup."""
        if smbus2 is None:
            raise ImportError("smbus2 not installed; install: pip install smbus2")
        try:
            return smbus2.SMBus(self._bus_num)
        except Exception as e:
            raise OSError(f"failed to open I²C bus {self._bus_num}: {e}") from e

    def _setup_once(self, bus: object) -> BMP280Calibration:
        """Verify chip ID and read calibration coefficients (once; cached)."""
        if self._calibration is not None:
            return self._calibration
        try:
            chip_id = bus.read_i2c_block_data(self._address, _REG_CHIP_ID, 1)[0]
        except Exception as e:
            raise OSError(f"failed to read BMP280 chip ID at 0x{self._address:02x}: {e}") from e
        if chip_id != _EXPECTED_CHIP_ID:
            raise OSError(
                f"unexpected chip ID 0x{chip_id:02x} at 0x{self._address:02x} "
                f"(expected 0x{_EXPECTED_CHIP_ID:02x} for BMP280)"
            )
        try:
            raw = bus.read_i2c_block_data(self._address, _REG_CALIB_START, _CALIB_LENGTH)
        except Exception as e:
            raise OSError(f"failed to read BMP280 calibration block: {e}") from e
        self._calibration = BMP280Calibration(bytes(raw))
        return self._calibration

    def _trigger_forced_measurement(self, bus: object) -> None:
        try:
            bus.write_byte_data(self._address, _REG_CONFIG, _CONFIG_NO_FILTER_I2C)
            bus.write_byte_data(self._address, _REG_CTRL_MEAS, _CTRL_MEAS_FORCED_OSRS_X1)
        except Exception as e:
            raise OSError(f"failed to trigger BMP280 forced measurement: {e}") from e

    def _wait_for_measurement(self, bus: object) -> None:
        deadline = time.monotonic() + _MEASUREMENT_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                status = bus.read_i2c_block_data(self._address, _REG_STATUS, 1)[0]
            except Exception as e:
                raise OSError(f"failed to read BMP280 status register: {e}") from e
            if not (status & _STATUS_MEASURING_BIT):
                return
            time.sleep(_MEASUREMENT_POLL_INTERVAL_S)
        # Timeout: proceed to read anyway (matches bmp280_hwtest.py — a stale
        # value is still preferable to hanging indefinitely; a genuinely dead
        # sensor will instead fail the subsequent data-block read).

    def read_pressure_hpa(self) -> float:
        """Read barometric pressure (hPa) from the BMP280.

        Raises OSError on any failure (bus open, chip-ID mismatch,
        calibration read, measurement trigger, status poll, data read, or a
        degenerate compensation division-by-zero).
        """
        bus = self._open_bus()
        try:
            cal = self._setup_once(bus)
            self._trigger_forced_measurement(bus)
            self._wait_for_measurement(bus)
            try:
                data = bus.read_i2c_block_data(self._address, _REG_DATA_START, _DATA_LENGTH)
            except Exception as e:
                raise OSError(f"failed to read BMP280 measurement data: {e}") from e
            press_msb, press_lsb, press_xlsb, temp_msb, temp_lsb, temp_xlsb = data
            raw_pressure = (press_msb << 12) | (press_lsb << 4) | (press_xlsb >> 4)
            raw_temperature = (temp_msb << 12) | (temp_lsb << 4) | (temp_xlsb >> 4)
            _, t_fine = _compensate_temperature(raw_temperature, cal)
            pressure_pa = _compensate_pressure(raw_pressure, t_fine, cal)
            return pressure_pa / 100.0
        finally:
            bus.close()


def bmp280_raw_read(bus_num: int = 1, address: int = 0x76) -> RawRead:
    """Factory: create a RawRead callable from a BMP280.

    Args:
        bus_num: I²C bus (e.g. 1 for /dev/i2c-1). Default: 1.
        address: BMP280 7-bit address. Default: 0x76.

    Returns a callable that reads pressure (hPa), or raises OSError on failure.
    """
    reader = BMP280Reader(bus_num=bus_num, address=address)

    def _read() -> float:
        return reader.read_pressure_hpa()

    return _read


class BMP280Driver(SensorDriver):
    """Real BMP280 hardware driver conforming to SensorDriver interface.

    Verifies chip ID and reads calibration once, then triggers a forced-mode
    conversion and reads compensated pressure (hPa) on every read. Wraps in a
    Sensor (P1 base.py) for health handling. Never raises; unhealthy reads
    return healthy=False, value=None (firmware discipline §02.8).
    """

    def __init__(self, *, bus_num: int = 1, address: int = 0x76) -> None:
        """Initialize the BMP280 driver.

        Args:
            bus_num: I²C bus number. Default: 1 (/dev/i2c-1).
            address: BMP280 7-bit I²C address. Default: 0x76.
        """
        self._sensor = Sensor(
            unit="hPa",
            raw_read=bmp280_raw_read(bus_num=bus_num, address=address),
        )

    def read(self):
        """Read BMP280 pressure (hPa). Never raises; returns healthy=False on failure."""
        return self._sensor.read()
