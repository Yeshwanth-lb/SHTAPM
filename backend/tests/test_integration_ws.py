"""M3.4 integration test — REAL full path: simulator → Mosquitto → backend → /ws.

Requires a running broker + paho + fastapi/httpx. Skips cleanly otherwise.

    POSTGRES_PASSWORD=dev docker compose up -d mosquitto
    MQTT_HOST=localhost MQTT_PORT=1883 pytest -m integration -q
"""

import os
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("paho.mqtt.client")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from simulator.generator import TelemetrySimulator  # noqa: E402
from simulator.publisher import MqttTelemetryPublisher  # noqa: E402
from simulator.roundtrip import broker_available  # noqa: E402
from simulator.timesource import now_iso_ms  # noqa: E402

HOST = os.environ.get("MQTT_HOST", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def broker():
    if not broker_available(HOST, PORT):
        pytest.skip(f"no MQTT broker reachable at {HOST}:{PORT}")
    return (HOST, PORT)


def test_mqtt_to_backend_to_ws(broker, monkeypatch):
    import paho.mqtt.client as mqtt

    host, port = broker
    monkeypatch.setenv("MQTT_HOST", host)
    monkeypatch.setenv("MQTT_PORT", str(port))

    with TestClient(app) as client:  # lifespan starts consumer against the real broker
        # wait for the backend consumer to connect + subscribe
        deadline = time.time() + 10.0
        while not app.state.telemetry_consumer.is_connected() and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)

        with client.websocket_connect("/ws?device_id=pump-01") as ws:
            pub = mqtt.Client()
            pub.connect(host, port)
            pub.loop_start()
            publisher = MqttTelemetryPublisher(pub, device_id="pump-01")
            sim = TelemetrySimulator(device_id="pump-01", seed=1337)
            try:
                # publish a few (QoS0) so the subscribed consumer catches at least one
                for _ in range(5):
                    publisher.publish(sim.next(now_iso_ms()))
                    time.sleep(0.1)
                frame = ws.receive_json()
            finally:
                pub.loop_stop()
                pub.disconnect()

    assert frame["type"] == "telemetry"
    assert frame["device_id"] == "pump-01"
    assert set(frame["sensors"].keys()) == {
        "temperature", "vibration", "pressure", "humidity", "gas", "current",
    }
