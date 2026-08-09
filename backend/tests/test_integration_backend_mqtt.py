"""M3.3 integration test — REAL path: simulator → Mosquitto → backend consumer.

Requires a running broker + paho. Skips cleanly otherwise. Reuses the existing
simulator publisher (no second publisher) and the backend consumer/store.

    POSTGRES_PASSWORD=dev docker compose up -d mosquitto
    MQTT_HOST=localhost MQTT_PORT=1883 pytest -m integration -q
"""

import os
import time

import pytest

from app.mqtt.consumer import TelemetryConsumer
from app.services.telemetry_store import TelemetryStore
from simulator.generator import TelemetrySimulator
from simulator.publisher import MqttTelemetryPublisher
from simulator.roundtrip import broker_available
from simulator.timesource import now_iso_ms

HOST = os.environ.get("MQTT_HOST", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def broker():
    if not broker_available(HOST, PORT):
        pytest.skip(f"no MQTT broker reachable at {HOST}:{PORT}")
    pytest.importorskip("paho.mqtt.client")
    return (HOST, PORT)


def test_simulator_to_backend_ingestion(broker):
    import paho.mqtt.client as mqtt

    host, port = broker
    store = TelemetryStore()
    consumer = TelemetryConsumer(store)
    consumer.start(host, port)

    pub_client = mqtt.Client()
    pub_client.connect(host, port)
    pub_client.loop_start()
    publisher = MqttTelemetryPublisher(pub_client, device_id="pump-01")
    sim = TelemetrySimulator(device_id="pump-01", seed=1337)

    try:
        deadline = time.time() + 10.0
        while not consumer.is_connected() and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)

        for _ in range(3):
            publisher.publish(sim.next(now_iso_ms()))
            time.sleep(0.05)

        while store.count < 3 and time.time() < deadline:
            time.sleep(0.02)
    finally:
        pub_client.loop_stop()
        pub_client.disconnect()
        consumer.stop()

    assert store.count >= 3
    assert consumer.error_count == 0
    latest = store.latest("pump-01")
    assert latest is not None and latest.device_id == "pump-01"
    assert set(latest.sensors.model_dump().keys()) == {
        "temperature", "vibration", "pressure", "humidity", "gas", "current",
    }
