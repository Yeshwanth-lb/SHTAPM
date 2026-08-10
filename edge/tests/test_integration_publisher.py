"""C3 integration test — REAL broker buffered-resume (skips if no broker/paho).

Deterministic unit tests (test_mqtt_publisher.py) are the primary gate; this
exercises the real reconnect path when a broker is available. It does NOT stop
the broker (that requires docker orchestration + is flaky in-sandbox); instead
it drives the publisher's disconnect/reconnect callbacks against a live broker
and asserts the buffered frames replay in order to a subscriber. Full
broker-stop/start replay is validated manually / by the unit suite.
"""

import json
import os
import time

import pytest
from app.schemas.build import build_telemetry

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from simulator.roundtrip import broker_available

HOST = os.environ.get("MQTT_HOST", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

pytestmark = pytest.mark.integration

SENSORS = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.42,
}


def _msg(seq):
    return build_telemetry("pump-int", "2026-08-10T12:00:00.000Z", SENSORS, seq)


@pytest.fixture(scope="module")
def broker():
    if not broker_available(HOST, PORT):
        pytest.skip(f"no MQTT broker reachable at {HOST}:{PORT}")
    pytest.importorskip("paho.mqtt.client")
    return (HOST, PORT)


def test_connect_online_and_publish_roundtrip(broker):
    import paho.mqtt.client as mqtt

    host, port = broker
    received: list[dict] = []
    status_seen: list[str] = []

    sub = mqtt.Client()

    def on_connect(c, u, f, rc):
        c.subscribe("shtapm/pump-int/telemetry", qos=0)
        c.subscribe("shtapm/pump-int/status", qos=1)

    def on_message(c, u, msg):
        if msg.topic.endswith("/status"):
            status_seen.append(msg.payload.decode())
        else:
            received.append(json.loads(msg.payload.decode()))

    sub.on_connect = on_connect
    sub.on_message = on_message
    sub.connect(host, port)
    sub.loop_start()

    pub = ResilientTelemetryPublisher(device_id="pump-int", rate_hz=10, client=None)
    pub.start(host, port)
    try:
        deadline = time.time() + 10
        while not pub.is_connected() and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)

        # simulate an outage purely at the publisher's state machine, then buffer
        pub._on_disconnect(pub._client, None, 0)  # noqa: SLF001 — drive state for test
        for i in range(5):
            pub.publish(_msg(i))  # buffered (publisher believes it is offline)
        # reconnect → drains buffered frames in order
        pub._on_connect(pub._client, None, None, 0)  # noqa: SLF001

        while len(received) < 5 and time.time() < deadline:
            time.sleep(0.05)
    finally:
        pub.stop()
        sub.loop_stop()
        sub.disconnect()

    seqs = [m["sample_seq"] for m in received[:5]]
    assert seqs == [0, 1, 2, 3, 4]  # FIFO order + sample_seq continuity preserved
    assert "online" in status_seen  # retained status observed
