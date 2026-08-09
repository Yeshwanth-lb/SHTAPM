"""M3.2 integration test — REAL Mosquitto round trip.

Requires a running broker + paho-mqtt. Skips cleanly (does NOT fail) when no
broker is reachable, so `pytest -q` stays green in environments without one.
To run it, start the project's broker and point env at it, e.g.:

    POSTGRES_PASSWORD=dev docker compose up -d mosquitto
    MQTT_HOST=localhost MQTT_PORT=1883 pytest -m integration -q
"""

import os

import pytest
from app.schemas.contracts import TelemetryMessage

from simulator.roundtrip import broker_available, run_roundtrip

HOST = os.environ.get("MQTT_HOST", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def broker():
    if not broker_available(HOST, PORT):
        pytest.skip(f"no MQTT broker reachable at {HOST}:{PORT}")
    try:
        import paho.mqtt.client  # noqa: F401
    except ModuleNotFoundError:
        pytest.skip("paho-mqtt not installed (pip install simulator/requirements.txt)")
    return (HOST, PORT)


def test_real_broker_roundtrip(broker):
    host, port = broker
    received = run_roundtrip(host, port, device_id="pump-01", count=3, seed=1337)

    assert len(received) == 3
    for msg in received:
        assert isinstance(msg, TelemetryMessage)
        TelemetryMessage.model_validate(msg.model_dump())  # frozen contract
        assert msg.device_id == "pump-01"
        assert set(msg.sensors.model_dump().keys()) == {
            "temperature",
            "vibration",
            "pressure",
            "humidity",
            "gas",
            "current",
        }
    # order preserved end to end
    assert [m.sample_seq for m in received] == [0, 1, 2]
