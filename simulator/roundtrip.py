"""Real-broker round-trip harness (M3.2).

Proves: simulator publishes → Mosquitto → subscriber receives → payload
validates against the frozen contract. Reused by the integration test and
runnable manually. paho-mqtt is imported lazily so importing this module (and
collecting the test) needs no paho; ``broker_available`` uses only stdlib so the
integration test can skip cleanly when no broker is reachable.

Host/port come from the caller (env-driven), never hardcoded secrets.
"""

from __future__ import annotations

import time

from app.schemas.contracts import TelemetryMessage

from simulator.generator import TelemetrySimulator
from simulator.publisher import MqttTelemetryPublisher
from simulator.subscriber import MqttTelemetrySubscriber
from simulator.timesource import now_iso_ms


def broker_available(host: str, port: int, timeout: float = 1.0) -> bool:
    """True if a TCP connection to the broker succeeds (stdlib only, no paho)."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_roundtrip(
    host: str,
    port: int,
    device_id: str = "pump-01",
    count: int = 3,
    seed: int = 1337,
    timeout: float = 10.0,
) -> list[TelemetryMessage]:
    """Publish ``count`` telemetry samples and return what the subscriber received."""
    import paho.mqtt.client as mqtt  # lazy: only needed for a real broker

    sub_client = mqtt.Client()
    collector = MqttTelemetrySubscriber(sub_client, device_id=device_id)
    sub_client.connect(host, port)
    sub_client.loop_start()

    pub_client = mqtt.Client()
    pub_client.connect(host, port)
    pub_client.loop_start()
    publisher = MqttTelemetryPublisher(pub_client, device_id=device_id)
    sim = TelemetrySimulator(device_id=device_id, seed=seed)

    try:
        # wait for the subscription to be established before publishing
        deadline = time.time() + timeout
        while not sub_client.is_connected() and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)

        for _ in range(count):
            publisher.publish(sim.next(now_iso_ms()))
            time.sleep(0.05)

        while len(collector.messages) < count and time.time() < deadline:
            time.sleep(0.02)
    finally:
        for c in (pub_client, sub_client):
            c.loop_stop()
            c.disconnect()

    if collector.errors:
        raise AssertionError(f"subscriber recorded contract errors: {collector.errors}")
    return collector.messages
