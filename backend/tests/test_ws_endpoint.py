"""M3.4 test — /ws endpoint delivers broadcast frames (TestClient, no broker)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("paho.mqtt.client")

from app.main import app  # noqa: E402
from app.schemas.contracts import SensorReadings, TelemetryMessage  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _msg(device_id: str = "pump-01", seq: int = 0) -> TelemetryMessage:
    return TelemetryMessage(
        device_id=device_id,
        ts="2026-08-09T12:00:00.000Z",
        sensors=SensorReadings(
            temperature=26.0,
            vibration=0.03,
            pressure=1013.0,
            humidity=45.0,
            gas=150.0,
            current=0.42,
        ),
        sample_seq=seq,
    )


def _no_broker(monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "127.0.0.1")
    monkeypatch.setenv("MQTT_PORT", "1")


def test_ws_receives_broadcast_frame(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            app.state.telemetry_broadcaster.publish_from_thread(_msg("pump-01", 3))
            frame = ws.receive_json()
    assert frame["type"] == "telemetry"
    assert frame["device_id"] == "pump-01"
    assert frame["sample_seq"] == 3


def test_ws_device_filter(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect("/ws?device_id=pump-02") as ws:
            b = app.state.telemetry_broadcaster
            b.publish_from_thread(_msg("pump-01"))  # filtered out
            b.publish_from_thread(_msg("pump-02"))  # delivered
            frame = ws.receive_json()
    assert frame["device_id"] == "pump-02"


def test_healthz_reports_ws_clients(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect("/ws"):
            body = client.get("/healthz").json()
            assert body["ws_clients"] >= 1
