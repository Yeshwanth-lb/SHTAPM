"""Standalone BMP280 hardware bench test (I²C, address 0x76) — NOT a driver.

Purpose: prove the physical BMP280 sensor + register map + Bosch compensation
formulas are correct on this exact wiring, BEFORE any edge/drivers/bmp280.py
production driver is written (same bring-up order already used for INA219,
DHT22, DS18B20, ADXL335). Deliberately does NOT use SensorDriver/Sensor
(edge/drivers/base.py) — no Reading, no health gate, no edge/main.py wiring.
Not collected by pytest; requires real I2C hardware to run.

Read strategy (evidence-based, not assumed): on this Pi, i2cdump's
block-style register reads succeeded consistently across five scans, while
single-byte i2cget / smbus2.read_byte_data() calls returned "Remote I/O
error". This script therefore uses read_i2c_block_data() for every register
read (calibration block, chip ID, measurement data) and never
read_byte_data() — matching what has actually been shown to work on this
wiring, not guessing at a fix for the intermittent single-byte failures.

Register map / compensation formulas: Bosch BMP280 datasheet (chip ID 0x58,
confirmed via i2cdump register 0xD0 on this board), Appendix B "Compensation
formula" — the 64-bit-integer reference version (exact; Python ints are
arbitrary-precision so this reproduces it exactly, no overflow masking
needed).

Run on the Pi (existing smbus2 dependency, already in edge/requirements.txt
and this venv — nothing new to install):
    PYTHONPATH=backend:. python edge/scripts/bmp280_hwtest.py

ADXL335 (SPI/MCP3008) is a completely separate bus/interface from BMP280
(I2C) — this script touches only I2C bus 1, address 0x76, and does not read,
write, or import anything related to ADXL335/spidev. Safe to run without
disturbing the connected ADXL335.
"""

from __future__ import annotations

import struct
import sys
import time

try:
    import smbus2
except ImportError:
    smbus2 = None  # type: ignore

I2C_BUS = 1
BMP280_ADDR = 0x76  # confirmed via i2cdetect/i2cdump on this board

REG_CALIB_START = 0x88
CALIB_LENGTH = 24  # dig_T1..T3, dig_P1..P9 — 12 fields x 2 bytes

REG_CHIP_ID = 0xD0
EXPECTED_CHIP_ID = 0x58  # confirmed via i2cdump on this board

REG_CTRL_MEAS = 0xF4
REG_CONFIG = 0xF5
REG_STATUS = 0xF3
STATUS_MEASURING_BIT = 0x08

REG_DATA_START = 0xF7  # press_msb, press_lsb, press_xlsb, temp_msb, temp_lsb, temp_xlsb
DATA_LENGTH = 6

# ctrl_meas: osrs_t=001 (x1), osrs_p=001 (x1), mode=01 (forced) -> 0b001_001_01
CTRL_MEAS_FORCED_OSRS_X1 = 0x25
# config: t_sb=000 (irrelevant in forced mode), filter=000 (off), spi3w_en=0 (I2C)
CONFIG_NO_FILTER_I2C = 0x00

_MAX_RETRIES = 3
_RETRY_DELAY_S = 0.05


class BMP280HardwareError(Exception):
    """Raised when the BMP280 cannot be read/configured after retries."""


def _retry_i2c(op_name: str, fn):
    """Run an I2C operation with a few retries — Remote I/O error has been
    observed to be intermittent on this wiring for single-byte transactions;
    block reads are used throughout, but retries add resilience regardless."""
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except OSError as e:
            last_error = e
            print(f"  [warn] {op_name} attempt {attempt}/{_MAX_RETRIES} failed: {e}")
            time.sleep(_RETRY_DELAY_S)
    raise BMP280HardwareError(f"{op_name} failed after {_MAX_RETRIES} attempts: {last_error}")


class BMP280Calibration:
    """Parsed calibration coefficients (dig_T1..T3, dig_P1..P9)."""

    def __init__(self, raw: bytes) -> None:
        (
            self.dig_T1, self.dig_T2, self.dig_T3,
            self.dig_P1, self.dig_P2, self.dig_P3, self.dig_P4,
            self.dig_P5, self.dig_P6, self.dig_P7, self.dig_P8, self.dig_P9,
        ) = struct.unpack("<HhhHhhhhhhhh", raw)


def read_chip_id(bus) -> int:
    data = _retry_i2c(
        "read chip ID (0xD0)",
        lambda: bus.read_i2c_block_data(BMP280_ADDR, REG_CHIP_ID, 1),
    )
    return data[0]


def read_calibration(bus) -> BMP280Calibration:
    raw = _retry_i2c(
        "read calibration block (0x88-0x9F)",
        lambda: bus.read_i2c_block_data(BMP280_ADDR, REG_CALIB_START, CALIB_LENGTH),
    )
    return BMP280Calibration(bytes(raw))


def trigger_forced_measurement(bus) -> None:
    _retry_i2c(
        "write config (0xF5)",
        lambda: bus.write_byte_data(BMP280_ADDR, REG_CONFIG, CONFIG_NO_FILTER_I2C),
    )
    _retry_i2c(
        "write ctrl_meas / trigger forced mode (0xF4)",
        lambda: bus.write_byte_data(BMP280_ADDR, REG_CTRL_MEAS, CTRL_MEAS_FORCED_OSRS_X1),
    )


def wait_for_measurement(bus, *, timeout_s: float = 0.1) -> None:
    """Poll the status register until the 'measuring' bit clears, or give up
    after timeout_s (osrs_t=1/osrs_p=1 typically completes in a few ms per
    datasheet — 0.1s is a generous margin, not a measured value)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = _retry_i2c(
            "read status (0xF3)",
            lambda: bus.read_i2c_block_data(BMP280_ADDR, REG_STATUS, 1),
        )[0]
        if not (status & STATUS_MEASURING_BIT):
            return
        time.sleep(0.005)
    print("  [warn] measurement did not clear 'measuring' status within timeout; reading anyway")


def read_raw_data(bus) -> tuple[int, int]:
    """Returns (raw_pressure, raw_temperature) — 20-bit ADC counts each."""
    data = _retry_i2c(
        "read measurement data (0xF7-0xFC)",
        lambda: bus.read_i2c_block_data(BMP280_ADDR, REG_DATA_START, DATA_LENGTH),
    )
    press_msb, press_lsb, press_xlsb, temp_msb, temp_lsb, temp_xlsb = data
    raw_pressure = (press_msb << 12) | (press_lsb << 4) | (press_xlsb >> 4)
    raw_temperature = (temp_msb << 12) | (temp_lsb << 4) | (temp_xlsb >> 4)
    return raw_pressure, raw_temperature


def compensate_temperature(adc_T: int, cal: BMP280Calibration) -> tuple[float, int]:
    """Bosch BMP280 datasheet, 64-bit integer compensation formula.
    Returns (temperature_degC, t_fine) — t_fine feeds pressure compensation."""
    var1 = (((adc_T >> 3) - (cal.dig_T1 << 1)) * cal.dig_T2) >> 11
    var2 = (((((adc_T >> 4) - cal.dig_T1) * ((adc_T >> 4) - cal.dig_T1)) >> 12) * cal.dig_T3) >> 14
    t_fine = var1 + var2
    temperature_c = ((t_fine * 5 + 128) >> 8) / 100.0
    return temperature_c, t_fine


def compensate_pressure(adc_P: int, t_fine: int, cal: BMP280Calibration) -> float:
    """Bosch BMP280 datasheet, 64-bit integer compensation formula.
    Returns pressure in Pa (divide by 100 for hPa)."""
    var1 = t_fine - 128000
    var2 = var1 * var1 * cal.dig_P6
    var2 = var2 + ((var1 * cal.dig_P5) << 17)
    var2 = var2 + (cal.dig_P4 << 35)
    var1 = ((var1 * var1 * cal.dig_P3) >> 8) + ((var1 * cal.dig_P2) << 12)
    var1 = (((1 << 47) + var1) * cal.dig_P1) >> 33
    if var1 == 0:
        print("  [warn] dig_P1 compensation var1 == 0; cannot compute pressure (would divide by zero)")
        return 0.0
    p = 1048576 - adc_P
    p = (((p << 31) - var2) * 3125) // var1
    var1 = (cal.dig_P9 * (p >> 13) * (p >> 13)) >> 25
    var2 = (cal.dig_P8 * p) >> 19
    p = ((p + var1 + var2) >> 8) + (cal.dig_P7 << 4)
    return p / 256.0


def main() -> int:
    if smbus2 is None:
        print("ERROR: smbus2 not importable in this environment.", file=sys.stderr)
        print("Expected already installed per edge/requirements.txt — check the venv.", file=sys.stderr)
        return 1

    print(f"BMP280 hardware test — bus {I2C_BUS}, address 0x{BMP280_ADDR:02x}")

    try:
        bus = smbus2.SMBus(I2C_BUS)
    except OSError as e:
        print(f"ERROR: failed to open I2C bus {I2C_BUS}: {e}", file=sys.stderr)
        return 1

    try:
        chip_id = read_chip_id(bus)
        print(f"chip ID (0xD0): 0x{chip_id:02x}")
        if chip_id != EXPECTED_CHIP_ID:
            print(f"  [warn] expected 0x{EXPECTED_CHIP_ID:02x} (BMP280) — got a different chip ID")

        cal = read_calibration(bus)
        print(
            "calibration: "
            f"dig_T1={cal.dig_T1} dig_T2={cal.dig_T2} dig_T3={cal.dig_T3} "
            f"dig_P1={cal.dig_P1} dig_P2={cal.dig_P2} dig_P3={cal.dig_P3} "
            f"dig_P4={cal.dig_P4} dig_P5={cal.dig_P5} dig_P6={cal.dig_P6} "
            f"dig_P7={cal.dig_P7} dig_P8={cal.dig_P8} dig_P9={cal.dig_P9}"
        )

        trigger_forced_measurement(bus)
        wait_for_measurement(bus)

        raw_pressure, raw_temperature = read_raw_data(bus)
        print(f"raw: pressure_adc={raw_pressure} temperature_adc={raw_temperature}")

        temperature_c, t_fine = compensate_temperature(raw_temperature, cal)
        pressure_pa = compensate_pressure(raw_pressure, t_fine, cal)
        pressure_hpa = pressure_pa / 100.0

        print()
        print(f"Temperature: {temperature_c:.2f} degC")
        print(f"Pressure:    {pressure_hpa:.2f} hPa")
        return 0

    except BMP280HardwareError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        bus.close()


if __name__ == "__main__":
    sys.exit(main())
