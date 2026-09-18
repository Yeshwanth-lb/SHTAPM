"""Standalone INA219 + ADXL335 logger for motor-load bench experiments.

WHY THIS EXISTS: the six-channel telemetry frame only publishes when ALL six
channels are healthy (edge/acquisition/sampler.py). A brushed DC motor running
next to the bench emits enough broadband electrical noise to corrupt the DHT22's
bit-banged single-wire protocol, so `temperature`/`humidity` go unhealthy and
NO frame is published -- observed on this bench, both channels failing together
because one physical DHT22 serves both (D028).

That blocks capturing the one relationship the digital twin actually needs:
current vs vibration under load. This script reads ONLY those two sensors,
directly through their existing production drivers, so the DHT22 problem is
irrelevant to it.

Diagnostics/bench tooling only -- same status as edge/scripts/hw_diagnostic.py
and edge/scripts/bmp280_hwtest.py. NOT production, NOT imported by edge/main.py,
NOT on any acceptance path, and it publishes nothing to MQTT.

RAW ADC COUNTS, NOT g: vibration is logged as the raw MCP3008 counts for X/Y/Z
rather than ADXL335Driver's g-value. That driver captures an at-rest baseline on
its FIRST read and reports deviation from it, so a g-value recorded while the
motor is already running would be measured against a poisoned zero point. Raw
counts are absolute and baseline-independent, so the analysis can choose its own
reference afterwards. The driver's g-value is logged alongside for reference
only -- never as the primary signal.

Run on the Pi (does NOT require stopping shtapm.service -- both read the same
sensors independently; SPI/I2C tolerate this, at the cost of occasional
contention retries):

    PYTHONPATH=backend:. python edge/scripts/load_capture.py out.jsonl

Ctrl+C to stop. Every line is one JSON sample.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from datetime import UTC, datetime

try:
    from edge.drivers.adxl335 import ADXL335Driver, ADXL335MCP3008Reader
    from edge.drivers.ina219 import INA219Driver
except ImportError as e:  # pragma: no cover - bench script
    print(f"ERROR: could not import edge drivers ({e}).", file=sys.stderr)
    print(
        "Run from the repo root: "
        "PYTHONPATH=backend:. python edge/scripts/load_capture.py out.jsonl",
        file=sys.stderr,
    )
    sys.exit(1)

# Bench wiring -- matches edge/main.py's _DEFAULT_CHANNEL_SPECS.
INA219_BUS = 1
INA219_ADDR = 0x40
ADXL335_X_CHANNEL = 0
ADXL335_Y_CHANNEL = 1
ADXL335_Z_CHANNEL = 2

SAMPLE_INTERVAL_S = 1.0

_running = {"go": True}


def _stop(*_a: object) -> None:
    _running["go"] = False


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: load_capture.py <output.jsonl>", file=sys.stderr)
        return 2
    out_path = sys.argv[1]

    raw_reader = ADXL335MCP3008Reader(
        x_channel=ADXL335_X_CHANNEL, y_channel=ADXL335_Y_CHANNEL, z_channel=ADXL335_Z_CHANNEL
    )
    vib_driver = ADXL335Driver(
        x_channel=ADXL335_X_CHANNEL, y_channel=ADXL335_Y_CHANNEL, z_channel=ADXL335_Z_CHANNEL
    )
    ina_driver = INA219Driver(bus_num=INA219_BUS, address=INA219_ADDR)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(f"logging to {out_path} (Ctrl+C to stop)")
    print(f"{'time':<14}{'current_A':>12}{'adc_x':>8}{'adc_y':>8}{'adc_z':>8}{'vib_g':>10}")

    written = 0
    with open(out_path, "a", encoding="utf-8") as fh:
        while _running["go"]:
            ts = (
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.")
                + f"{datetime.now(UTC).microsecond // 1000:03d}Z"
            )

            # Each read is independent: one sensor failing must not stop the other,
            # which is the entire reason this script exists.
            try:
                x, y, z = raw_reader.read_raw_xyz()
            except Exception as e:
                x = y = z = None
                print(f"  [warn] ADXL335 raw read failed: {e}", file=sys.stderr)

            vib = vib_driver.read()
            cur = ina_driver.read()

            record = {
                "ts": ts,
                "current_a": cur.value if cur.healthy else None,
                "current_healthy": cur.healthy,
                "adc_x": x,
                "adc_y": y,
                "adc_z": z,
                "vibration_g_driver": vib.value if vib.healthy else None,
                "vibration_healthy": vib.healthy,
            }
            fh.write(json.dumps(record) + "\n")
            fh.flush()  # survive an abrupt kill; a bench capture is not worth buffering
            written += 1

            print(
                f"{ts[11:19]:<14}"
                f"{(f'{cur.value:.6f}' if cur.healthy else 'FAIL'):>12}"
                f"{(x if x is not None else '-'):>8}"
                f"{(y if y is not None else '-'):>8}"
                f"{(z if z is not None else '-'):>8}"
                f"{(f'{vib.value:.4f}' if vib.healthy else 'FAIL'):>10}"
            )
            time.sleep(SAMPLE_INTERVAL_S)

    print(f"\nstopped; {written} samples written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
