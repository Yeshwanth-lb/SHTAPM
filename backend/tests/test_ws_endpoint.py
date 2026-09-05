"""M3.4 test — /ws endpoint delivers broadcast frames (TestClient, no broker).
P4-M6 adds auth + device-scoping coverage."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("paho.mqtt.client")

from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Device, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
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
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-not-real")


def _seed_user(app, role: UserRole, owned_device_ids: tuple[str, ...] = ()) -> str:
    """Insert a user (+ devices it owns) directly and return a valid access
    token — bypasses the real login endpoint since this suite tests the WS
    layer's own auth check, not login (already covered by test_auth_api.py)."""
    with app.state.db_sessionmaker() as db:
        user = User(email=f"{role.value}@example.com", password_hash="x", role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        for device_id in owned_device_ids:
            db.add(Device(device_id=device_id, name=device_id, owner_user_id=user.id))
        db.commit()
        return create_access_token(str(user.id), role.value, app.state.auth_settings)


def test_ws_requires_token(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client, pytest.raises(Exception):  # noqa: B017
        with client.websocket_connect("/ws"):
            pass


def test_ws_rejects_invalid_token(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client, pytest.raises(Exception):  # noqa: B017
        with client.websocket_connect("/ws?token=not-a-real-jwt"):
            pass


def test_ws_receives_broadcast_frame(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client:
        token = _seed_user(app, UserRole.admin)
        with client.websocket_connect(f"/ws?token={token}") as ws:
            app.state.telemetry_broadcaster.publish_from_thread(_msg("pump-01", 3))
            frame = ws.receive_json()
    assert frame["type"] == "telemetry"
    assert frame["device_id"] == "pump-01"
    assert frame["sample_seq"] == 3


def test_ws_device_filter(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client:
        token = _seed_user(app, UserRole.admin)
        with client.websocket_connect(f"/ws?token={token}&device_id=pump-02") as ws:
            b = app.state.telemetry_broadcaster
            b.publish_from_thread(_msg("pump-01"))  # filtered out
            b.publish_from_thread(_msg("pump-02"))  # delivered
            frame = ws.receive_json()
    assert frame["device_id"] == "pump-02"


def test_ws_non_admin_scoped_to_owned_devices_only(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client:
        token = _seed_user(app, UserRole.operator, owned_device_ids=("pump-01",))
        with client.websocket_connect(f"/ws?token={token}") as ws:  # no device_id filter
            b = app.state.telemetry_broadcaster
            b.publish_from_thread(_msg("pump-02"))  # not owned — must be filtered
            b.publish_from_thread(_msg("pump-01"))  # owned — delivered
            frame = ws.receive_json()
    assert frame["device_id"] == "pump-01"


def test_ws_non_admin_cannot_request_unowned_device_id(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client:
        token = _seed_user(app, UserRole.operator, owned_device_ids=("pump-01",))
        with pytest.raises(Exception), client.websocket_connect(  # noqa: B017
            f"/ws?token={token}&device_id=pump-02"
        ):
            pass


def test_healthz_reports_ws_clients(monkeypatch):
    _no_broker(monkeypatch)
    with TestClient(app) as client:
        token = _seed_user(app, UserRole.admin)
        with client.websocket_connect(f"/ws?token={token}"):
            body = client.get("/healthz").json()
            assert body["ws_clients"] >= 1
