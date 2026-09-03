"""SHTAPM edge acquisition runtime — mixed hardware/fake drivers.

Runs the C1→C2→C3 pipeline with:
  - Real ADXL335 vibration sensor via MCP3008/SPI0 CE0
  - Real BMP280 pressure sensor via I²C (bus 1, address 0x76)
  - Fake drivers for the remaining channels (temperature, humidity, gas,
    current)

    ADXL335 + BMP280 + fake drivers → Sampler → TelemetryMessage → ResilientTelemetryPublisher → Mosquitto

ADXL335 and BMP280 are real because they're the two sensors currently wired
to the Pi — INA219, DHT22, and DS18B20 are implemented (edge/drivers/
ina219.py, dht22.py, ds18b20.py, each independently hardware-validated
earlier) but temporarily physically disconnected from this bench, so they'd
be permanently unhealthy here and block every frame (Sampler.sample_once()
requires all six channels healthy). When they're reconnected, re-add their
imports and `drivers[channel] = XDriver()` lines exactly as before (see git
history: commits e40887c, 43f2a54/e35ca5b, and the INA219 wiring predating
this file's docstring) — no other change needed.

The frozen six-channel telemetry contract is preserved. Thin by design
(env + wiring + signals) — the logic lives in the tested runtime/sampler/publisher.

    PYTHONPATH=backend:. python -m edge
"""

from __future__ import annotations

import os
import signal
import time

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.runtime import AcquisitionRuntime
from edge.acquisition.sampler import Sampler
from edge.drivers.adxl335 import ADXL335Driver
from edge.drivers.bmp280 import BMP280Driver
from edge.drivers.fake import fake_drivers

# Plausible steady-state constants for fake sensors (dev only — not authoritative specs).
# The "vibration"/"pressure" values are placeholders; replaced by real drivers below.
# temperature/humidity/current are fake for now — see module docstring
# (INA219/DHT22/DS18B20 are implemented but currently physically disconnected).
_DEV_VALUES = {
    "temperature": 26.0,
    "vibration": 0.03,  # Placeholder; replaced by ADXL335Driver
    "pressure": 1013.0,  # Placeholder; replaced by BMP280Driver
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.0,
}


def main() -> None:
    device_id = os.environ.get("DEVICE_ID", "pump-01")
    rate_hz = float(os.environ.get("SAMPLE_RATE_HZ", "1"))
    host = os.environ.get("EDGE_MQTT_HOST", "localhost")
    port = int(os.environ.get("EDGE_MQTT_PORT", "1883"))

    # Create fake drivers for four channels (temperature, humidity, gas, current)
    drivers = fake_drivers(_DEV_VALUES)

    # Replace the fake vibration driver with real ADXL335 (MCP3008 over SPI0 CE0) —
    # physically connected; see module docstring.
    drivers["vibration"] = ADXL335Driver(bus=0, device=0)

    # Replace the fake pressure driver with real BMP280 (I²C bus 1, address 0x76) —
    # physically connected; see module docstring.
    drivers["pressure"] = BMP280Driver(bus_num=1, address=0x76)

    sampler = Sampler(device_id=device_id, drivers=drivers)
    publisher = ResilientTelemetryPublisher(device_id=device_id, rate_hz=rate_hz)
    publisher.start(host, port)
    runtime = AcquisitionRuntime(sampler=sampler, publisher=publisher, rate_hz=rate_hz)

    running = {"go": True}

    def _stop(*_a: object) -> None:
        running["go"] = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(
        f"[edge] MIXED HW/DEV: real ADXL335 (vibration) + real BMP280 (pressure) + "
        f"fake drivers (temperature, humidity, gas, current) → "
        f"{publisher.telemetry_topic} at {rate_hz} Hz (Ctrl-C to stop)"
    )
    try:
        runtime.run(should_continue=lambda: running["go"], sleep=time.sleep)
    finally:
        runtime.stop()
        print("[edge] stopped (status offline)")


if __name__ == "__main__":
    main()
