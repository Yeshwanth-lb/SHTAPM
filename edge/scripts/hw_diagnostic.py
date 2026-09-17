"""Standalone multi-sensor hardware diagnostic for the SHTAPM Raspberry Pi 5
bench (P1 · diagnostics only — NOT a production driver, NOT part of the
frozen six-channel telemetry contract, NOT imported by edge/main.py).

Tests, using EXISTING production driver code wherever a public API exists:

  DHT22    - GPIO17 (shared reader)      -> edge.drivers.dht22_adafruit
             DHT22AdafruitTemperatureDriver + DHT22AdafruitDriver
  ADXL335  - MCP3008 CH0/CH1/CH2 (SPI0)  -> edge.drivers.adxl335
             ADXL335MCP3008Reader (raw X/Y/Z) + ADXL335Driver (vibration g)
  BMP280   - I2C bus 1, 0x76             -> edge.drivers.bmp280.BMP280Driver
             (pressure, production public API)
  INA219   - I2C bus 1, 0x40             -> edge.drivers.ina219.INA219Driver
  MQ135    - AO -> divider -> MCP3008 CH3 -> NO driver exists in this repo
             (edge/drivers/registry.py: "gas" has no real driver implemented;
             edge/main.py wires it as a fake constant). This script reuses
             the only existing MCP3008 SPI-read code (ADXL335MCP3008Reader)
             to read a real raw ADC count/voltage on CH3. It does NOT invent
             a ppm calibration curve; ppm is reported as NOT IMPLEMENTED.

BMP280 TEMPERATURE DEVIATION: BMP280Driver's public read() intentionally
exposes pressure only -- the `temperature` channel is DHT22-sourced by
design (D027/D028), and BMP280's on-chip temperature is computed internally
during pressure compensation but never returned. No production API exists
for it. To still show it here, this script reuses BMP280Reader's own
private read sequence and the module's private compensation functions
(same Bosch formulas, not reimplemented) -- diagnostic only. This value
must never be treated as the pipeline's `temperature` channel.

Never fakes a value: every PASS/FAIL below reflects a real read attempt.
Does not modify, import into, or change the behavior of edge/main.py or
any production driver.

Run on the Pi:
    PYTHONPATH=backend:. python edge/scripts/hw_diagnostic.py
"""

from __future__ import annotations

import sys
import time

try:
    from edge.drivers import adxl335 as adxl335_mod
    from edge.drivers import bmp280 as bmp280_mod
    from edge.drivers.adxl335 import ADXL335Driver, ADXL335MCP3008Reader
    from edge.drivers.bmp280 import BMP280Driver
    from edge.drivers.dht22_adafruit import (
        DHT22AdafruitDriver,
        DHT22AdafruitTemperatureDriver,
    )
    from edge.drivers.ina219 import INA219Driver
except ImportError as e:
    print(f"ERROR: could not import edge drivers ({e}).", file=sys.stderr)
    print(
        "Run from the repo root with: PYTHONPATH=backend:. python edge/scripts/hw_diagnostic.py",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Bench wiring (matches the physical setup described for this diagnostic run)
# ---------------------------------------------------------------------------
DHT22_PIN = 17
ADXL335_X_CHANNEL = 0
ADXL335_Y_CHANNEL = 1
ADXL335_Z_CHANNEL = 2
BMP280_BUS = 1
BMP280_ADDR = 0x76
INA219_BUS = 1
INA219_ADDR = 0x40
MQ135_MCP3008_CHANNEL = 3  # AO -> divider -> MCP3008 CH3, DO unused

N_READINGS = 5
# DHT22 has a hardware/library-enforced ~2s minimum between measurements
# (see edge/drivers/dht22_adafruit.py); this interval is used between every
# iteration (all sensors) for simplicity and to give each iteration a fresh
# DHT22 measurement rather than a throttled repeat.
READING_INTERVAL_S = 2.5


def _mark(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def read_bmp280_temperature_and_pressure(bus_num: int, address: int) -> tuple[float, float]:
    """Diagnostic-only: reuses BMP280Reader's own private read sequence and
    the module's private Bosch compensation functions to obtain BOTH
    temperature (degC) and pressure (hPa) from one forced measurement.

    Not a production API -- BMP280Driver.read() (used separately below for
    the official pressure PASS/FAIL) never returns temperature, by design.
    Raises OSError/ImportError on any failure, same as the production code
    this reuses.
    """
    reader = bmp280_mod.BMP280Reader(bus_num=bus_num, address=address)
    bus = reader._open_bus()
    try:
        cal = reader._setup_once(bus)
        reader._trigger_forced_measurement(bus)
        reader._wait_for_measurement(bus)
        data = bus.read_i2c_block_data(
            address, bmp280_mod._REG_DATA_START, bmp280_mod._DATA_LENGTH
        )
        press_msb, press_lsb, press_xlsb, temp_msb, temp_lsb, temp_xlsb = data
        raw_pressure = (press_msb << 12) | (press_lsb << 4) | (press_xlsb >> 4)
        raw_temperature = (temp_msb << 12) | (temp_lsb << 4) | (temp_xlsb >> 4)
        temperature_c, t_fine = bmp280_mod._compensate_temperature(raw_temperature, cal)
        pressure_pa = bmp280_mod._compensate_pressure(raw_pressure, t_fine, cal)
        return temperature_c, pressure_pa / 100.0
    finally:
        bus.close()


def read_mq135_raw_adc(channel: int) -> tuple[int, float]:
    """Reuses the ONLY existing MCP3008 SPI-read code in this repo
    (ADXL335MCP3008Reader) to read a raw ADC count on an arbitrary MCP3008
    channel. Pointing all three of its (x/y/z) channel args at the same
    channel means all three returned values are that one channel's raw
    count -- this is not an ADXL335 reading, it is reuse of the shared
    MCP3008 transfer protocol only. No MQ135 driver exists to reuse instead.

    Returns (raw_adc_count, voltage). Raises OSError/ImportError on failure.
    """
    reader = ADXL335MCP3008Reader(x_channel=channel, y_channel=channel, z_channel=channel)
    raw_x, _raw_y, _raw_z = reader.read_raw_xyz()
    voltage = raw_x * (adxl335_mod._MCP3008_VREF_VOLTS / adxl335_mod._ADC_COUNTS)
    return raw_x, voltage


def main() -> int:
    print("=" * 70)
    print("SHTAPM Raspberry Pi 5 — standalone hardware diagnostic")
    print(f"Readings per sensor: {N_READINGS}, interval: {READING_INTERVAL_S}s")
    print("=" * 70)

    dht22_temp_driver = DHT22AdafruitTemperatureDriver(pin=DHT22_PIN)
    dht22_hum_driver = DHT22AdafruitDriver(pin=DHT22_PIN)
    adxl335_raw_reader = ADXL335MCP3008Reader(
        x_channel=ADXL335_X_CHANNEL, y_channel=ADXL335_Y_CHANNEL, z_channel=ADXL335_Z_CHANNEL
    )
    adxl335_driver = ADXL335Driver(
        x_channel=ADXL335_X_CHANNEL, y_channel=ADXL335_Y_CHANNEL, z_channel=ADXL335_Z_CHANNEL
    )
    bmp280_driver = BMP280Driver(bus_num=BMP280_BUS, address=BMP280_ADDR)
    ina219_driver = INA219Driver(bus_num=INA219_BUS, address=INA219_ADDR)

    results: dict[str, list[bool]] = {
        "dht22_temperature": [],
        "dht22_humidity": [],
        "adxl335": [],
        "bmp280_pressure": [],
        "bmp280_temperature_diag": [],
        "ina219": [],
        "mq135_raw_adc": [],
    }

    for i in range(1, N_READINGS + 1):
        print(f"\n--- Reading {i}/{N_READINGS} ---")

        # DHT22 temperature
        try:
            reading = dht22_temp_driver.read()
            ok = reading.healthy and reading.value is not None
            print(
                f"DHT22 temperature: value={reading.value} unit={reading.unit} "
                f"healthy={reading.healthy} -> {_mark(ok)}"
            )
            results["dht22_temperature"].append(ok)
        except Exception as e:
            print(f"DHT22 temperature: EXCEPTION {e!r} -> FAIL")
            results["dht22_temperature"].append(False)

        # DHT22 humidity
        try:
            reading = dht22_hum_driver.read()
            ok = reading.healthy and reading.value is not None
            print(
                f"DHT22 humidity: value={reading.value} unit={reading.unit} "
                f"healthy={reading.healthy} -> {_mark(ok)}"
            )
            results["dht22_humidity"].append(ok)
        except Exception as e:
            print(f"DHT22 humidity: EXCEPTION {e!r} -> FAIL")
            results["dht22_humidity"].append(False)

        # ADXL335: raw X/Y/Z + production vibration-magnitude result
        try:
            x, y, z = adxl335_raw_reader.read_raw_xyz()
            vib_reading = adxl335_driver.read()
            ok = vib_reading.healthy and vib_reading.value is not None
            note = " (first read defines baseline, 0.0 expected)" if i == 1 else ""
            print(
                f"ADXL335 raw: X={x} Y={y} Z={z} counts | "
                f"vibration={vib_reading.value} {vib_reading.unit} "
                f"healthy={vib_reading.healthy} -> {_mark(ok)}{note}"
            )
            results["adxl335"].append(ok)
        except Exception as e:
            print(f"ADXL335: EXCEPTION {e!r} -> FAIL")
            results["adxl335"].append(False)

        # BMP280 pressure (official production public API)
        try:
            reading = bmp280_driver.read()
            ok = reading.healthy and reading.value is not None
            print(
                f"BMP280 pressure: value={reading.value} unit={reading.unit} "
                f"healthy={reading.healthy} -> {_mark(ok)}"
            )
            results["bmp280_pressure"].append(ok)
        except Exception as e:
            print(f"BMP280 pressure: EXCEPTION {e!r} -> FAIL")
            results["bmp280_pressure"].append(False)

        # BMP280 temperature (diagnostic-only, see module docstring)
        try:
            temp_c, _pressure_hpa = read_bmp280_temperature_and_pressure(
                BMP280_BUS, BMP280_ADDR
            )
            print(
                f"BMP280 temperature (diagnostic-only, NOT the pipeline "
                f"`temperature` channel): value={temp_c:.2f} unit=degC -> PASS"
            )
            results["bmp280_temperature_diag"].append(True)
        except Exception as e:
            print(f"BMP280 temperature (diagnostic-only): EXCEPTION {e!r} -> FAIL")
            results["bmp280_temperature_diag"].append(False)

        # INA219 current
        try:
            reading = ina219_driver.read()
            ok = reading.healthy and reading.value is not None
            print(
                f"INA219 current: value={reading.value} unit={reading.unit} "
                f"healthy={reading.healthy} -> {_mark(ok)}"
            )
            results["ina219"].append(ok)
        except Exception as e:
            print(f"INA219: EXCEPTION {e!r} -> FAIL")
            results["ina219"].append(False)

        # MQ135 — raw MCP3008 analog path only; no driver, no ppm calibration
        try:
            raw_count, voltage = read_mq135_raw_adc(MQ135_MCP3008_CHANNEL)
            print(
                f"MQ135 raw ADC (CH{MQ135_MCP3008_CHANNEL}): count={raw_count} "
                f"voltage={voltage:.3f}V -> PASS (raw analog path only; "
                f"no MQ135 driver/ppm calibration exists in this repo)"
            )
            results["mq135_raw_adc"].append(True)
        except Exception as e:
            print(f"MQ135 raw ADC (CH{MQ135_MCP3008_CHANNEL}): EXCEPTION {e!r} -> FAIL")
            results["mq135_raw_adc"].append(False)

        if i < N_READINGS:
            time.sleep(READING_INTERVAL_S)

    def _summary_line(label: str, key: str) -> str:
        flags = results[key]
        overall = "PASS" if flags and all(flags) else "FAIL"
        passed = sum(flags)
        return f"{label}: {overall} ({passed}/{len(flags)} readings healthy)"

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(_summary_line("DHT22 temperature", "dht22_temperature"))
    print(_summary_line("DHT22 humidity", "dht22_humidity"))
    print(_summary_line("ADXL335", "adxl335"))
    print(_summary_line("BMP280 pressure", "bmp280_pressure"))
    print(
        _summary_line("BMP280 temperature (diagnostic-only)", "bmp280_temperature_diag")
    )
    print(_summary_line("INA219", "ina219"))
    mq_flags = results["mq135_raw_adc"]
    mq_overall = "PASS" if mq_flags and all(mq_flags) else "FAIL"
    print(
        f"MQ135: {mq_overall} (raw ADC path, {sum(mq_flags)}/{len(mq_flags)} readings) "
        f"/ NOT IMPLEMENTED (calibrated ppm — no MQ135 driver exists)"
    )
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
