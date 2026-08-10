"""C2→C3 runtime integration — REAL Mosquitto (skips if no broker/paho).

Full hardware-free pipeline: fake drivers → Sampler → ResilientTelemetryPublisher
→ Mosquitto → subscriber. Asserts telemetry topic/ordering + retained
online/offline status. Deterministic unit tests (test_runtime.py) are the
primary gate.
"""

import json
import os
import time

import pytest

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.runtime import AcquisitionRuntime
from edge.acquisition.sampler import Sampler
from edge.drivers.fake import fake_drivers
from simulator.roundtrip import broker_available

HOST = os.environ.get("MQTT_HOST", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

pytestmark = pytest.mark.integration

VALUES = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.42,
}
DEVICE = "pump-rt"


@pytest.fixture(scope="module")
def broker():
    if not broker_available(HOST, PORT):
        pytest.skip(f"no MQTT broker reachable at {HOST}:{PORT}")
    pytest.importorskip("paho.mqtt.client")
    return (HOST, PORT)


def test_pipeline_publishes_in_order_with_status(broker):
    import paho.mqtt.client as mqtt

    host, port = broker
    telemetry: list[dict] = []
    status: list[str] = []

    sub = mqtt.Client()

    def on_connect(c, u, f, rc):
        c.subscribe(f"shtapm/{DEVICE}/telemetry", qos=0)
        c.subscribe(f"shtapm/{DEVICE}/status", qos=1)

    def on_message(c, u, msg):
        (status if msg.topic.endswith("/status") else telemetry).append(
            msg.payload.decode()
            if msg.topic.endswith("/status")
            else json.loads(msg.payload.decode())
        )

    sub.on_connect = on_connect
    sub.on_message = on_message
    sub.connect(host, port)
    sub.loop_start()

    sampler = Sampler(device_id=DEVICE, drivers=fake_drivers(VALUES))
    publisher = ResilientTelemetryPublisher(device_id=DEVICE, rate_hz=10)
    publisher.start(host, port)
    runtime = AcquisitionRuntime(sampler=sampler, publisher=publisher, rate_hz=10)

    try:
        deadline = time.time() + 10
        while not publisher.is_connected() and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)  # let subscriber subscribe + retained online arrive

        n = 5
        calls = {"i": 0}

        def cont():
            calls["i"] += 1
            return calls["i"] <= n

        runtime.run(should_continue=cont, sleep=lambda _p: time.sleep(0.05))

        while len(telemetry) < n and time.time() < deadline:
            time.sleep(0.05)
    finally:
        runtime.stop()  # graceful offline
        time.sleep(0.2)
        sub.loop_stop()
        sub.disconnect()

    assert [m["sample_seq"] for m in telemetry[:5]] == [0, 1, 2, 3, 4]
    assert all(set(m["sensors"].keys()) == set(VALUES) for m in telemetry[:5])
    assert "online" in status
    assert "offline" in status  # graceful shutdown published retained offline
