"""SHTAPM edge acquisition runtime — mixed hardware/fake drivers.

Runs the C1→C2→C3 pipeline with:
  - Real INA219 current sensor over I²C (0x40 on /dev/i2c-1)
  - Real DHT22 humidity sensor via the kernel IIO interface (GPIO17)
  - Fake drivers for the remaining channels (temperature, vibration, pressure, gas)

    INA219 + DHT22 + fake drivers → Sampler → TelemetryMessage → ResilientTelemetryPublisher → Mosquitto

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
from edge.drivers.dht22 import DHT22Driver
from edge.drivers.fake import fake_drivers
from edge.drivers.ina219 import INA219Driver

# Plausible steady-state constants for fake sensors (dev only — not authoritative specs).
# The "current" and "humidity" values are placeholders; replaced by real drivers below.
_DEV_VALUES = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,  # Placeholder; replaced by DHT22Driver
    "gas": 150.0,
    "current": 0.0,  # Placeholder; replaced by INA219Driver
}


def main() -> None:
    device_id = os.environ.get("DEVICE_ID", "pump-01")
    rate_hz = float(os.environ.get("SAMPLE_RATE_HZ", "1"))
    host = os.environ.get("EDGE_MQTT_HOST", "localhost")
    port = int(os.environ.get("EDGE_MQTT_PORT", "1883"))

    # Create fake drivers for four channels (temperature, vibration, pressure, gas)
    drivers = fake_drivers(_DEV_VALUES)

    # Replace the fake current driver with real INA219 (bus 1, address 0x40)
    # Calibrated for 5A max expected current, 0.1Ω shunt resistor
    drivers["current"] = INA219Driver(
        bus_num=1, address=0x40, max_expected_amps=5.0, shunt_ohms=0.1
    )

    # Replace the fake humidity driver with real DHT22 (kernel dht11 IIO driver, GPIO17)
    drivers["humidity"] = DHT22Driver()

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
        f"[edge] MIXED HW/DEV: real INA219 (current) + real DHT22 (humidity) + "
        f"fake drivers → {publisher.telemetry_topic} at {rate_hz} Hz (Ctrl-C to stop)"
    )
    try:
        runtime.run(should_continue=lambda: running["go"], sleep=time.sleep)
    finally:
        runtime.stop()
        print("[edge] stopped (status offline)")


if __name__ == "__main__":
    main()
