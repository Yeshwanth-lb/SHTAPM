"""SHTAPM edge acquisition runtime — mixed hardware/fake drivers.

Runs the C1→C2→C3 pipeline with:
  - Real DS18B20 temperature probe via the kernel 1-Wire interface (GPIO4)
  - Fake drivers for the remaining channels (vibration, pressure, humidity,
    gas, current)

    DS18B20 + fake drivers → Sampler → TelemetryMessage → ResilientTelemetryPublisher → Mosquitto

DS18B20 is real because it's the only sensor currently wired to the Pi —
ADXL335, BMP280, INA219, and DHT22 are implemented (edge/drivers/adxl335.py,
bmp280.py, ina219.py, dht22.py, each independently hardware-validated
earlier) but temporarily physically disconnected from this bench, so they'd
be permanently unhealthy here and block every frame (Sampler.sample_once()
requires all six channels healthy). When they're reconnected, re-add their
imports and `drivers[channel] = XDriver()` lines exactly as before (see git
history: commits d419d6b, 85bbe42, 43f2a54/e35ca5b, and the INA219 wiring
predating this file's docstring) — no other change needed.

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
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.fake import fake_drivers

# Plausible steady-state constants for fake sensors (dev only — not authoritative specs).
# The "temperature" value is a placeholder; replaced by the real driver below.
# vibration/pressure/humidity/gas/current are fake for now — see module docstring
# (ADXL335/BMP280/INA219/DHT22 are implemented but currently physically disconnected).
_DEV_VALUES = {
    "temperature": 26.0,  # Placeholder; replaced by DS18B20Driver
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.0,
}


def main() -> None:
    device_id = os.environ.get("DEVICE_ID", "pump-01")
    rate_hz = float(os.environ.get("SAMPLE_RATE_HZ", "1"))
    host = os.environ.get("EDGE_MQTT_HOST", "localhost")
    port = int(os.environ.get("EDGE_MQTT_PORT", "1883"))

    # Create fake drivers for five channels (vibration, pressure, humidity, gas, current)
    drivers = fake_drivers(_DEV_VALUES)

    # Replace the fake temperature driver with real DS18B20 (kernel 1-Wire driver, GPIO4) —
    # the only sensor currently physically connected; see module docstring.
    drivers["temperature"] = DS18B20Driver()

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
        f"[edge] MIXED HW/DEV: real DS18B20 (temperature) + fake drivers "
        f"(vibration, pressure, humidity, gas, current) → "
        f"{publisher.telemetry_topic} at {rate_hz} Hz (Ctrl-C to stop)"
    )
    try:
        runtime.run(should_continue=lambda: running["go"], sleep=time.sleep)
    finally:
        runtime.stop()
        print("[edge] stopped (status offline)")


if __name__ == "__main__":
    main()
