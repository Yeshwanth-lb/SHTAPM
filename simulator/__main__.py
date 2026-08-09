"""CLI entry point: run the hardware-free telemetry simulator at 1 Hz.

    PYTHONPATH=backend:. python -m simulator

Reads DEVICE_ID / SAMPLE_RATE_HZ / EDGE_MQTT_HOST / EDGE_MQTT_PORT from the
environment (TRD §02.7). Builds a real paho-mqtt client and publishes frozen
telemetry to shtapm/{device_id}/telemetry.

Live publishing against a running broker is exercised end-to-end in M3.2+
(when the backend subscribes). This loop itself is intentionally thin (timing +
I/O), so it is not unit-tested; the deterministic generator and the publisher
serialization ARE unit-tested.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from simulator.generator import TelemetrySimulator
from simulator.publisher import MqttTelemetryPublisher


def _now_iso_ms() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    )


def main() -> None:
    device_id = os.environ.get("DEVICE_ID", "pump-01")
    rate_hz = float(os.environ.get("SAMPLE_RATE_HZ", "1"))
    host = os.environ.get("EDGE_MQTT_HOST", "localhost")
    port = int(os.environ.get("EDGE_MQTT_PORT", "1883"))

    import paho.mqtt.client as mqtt  # imported here so tests need no paho

    client = mqtt.Client()
    client.connect(host, port)
    client.loop_start()

    sim = TelemetrySimulator(device_id=device_id)
    publisher = MqttTelemetryPublisher(client, device_id=device_id)
    period = 1.0 / rate_hz

    print(f"[simulator] publishing to {publisher.topic} at {rate_hz} Hz (Ctrl-C to stop)")
    try:
        while True:
            publisher.publish(sim.next(_now_iso_ms()))
            time.sleep(period)
    except KeyboardInterrupt:
        print("\n[simulator] stopped")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
