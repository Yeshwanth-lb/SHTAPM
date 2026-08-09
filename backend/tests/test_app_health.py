"""M3.3 test — FastAPI app boots (lifespan starts the consumer) and /healthz
responds even with no broker reachable (graceful degradation).

Requires fastapi + httpx + paho (lifespan calls consumer.start → imports paho).
"""

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("paho.mqtt.client")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_healthz_ok_without_broker(monkeypatch):
    # point at an almost-certainly-dead port so no broker is required
    monkeypatch.setenv("MQTT_HOST", "127.0.0.1")
    monkeypatch.setenv("MQTT_PORT", "1")
    with TestClient(app) as client:  # triggers lifespan start/stop
        r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mqtt_connected"] is False
    assert body["telemetry_count"] == 0
    assert body["devices"] == []
