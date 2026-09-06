"""P4-M4 — REST API tests (Doc05 §05.7), Happy/Edge/Sad per Doc06 convention.

Standalone FastAPI app (auth + devices + alerts + users + system routers)
with ``get_db``/``get_auth_settings`` overridden — same isolation pattern as
``test_auth_api.py``, deliberately not ``app.main.app`` (MQTT lifespan).
``/api/system/health`` reads ``request.app.state.telemetry_*`` directly, so
this fixture stands in small fakes for those three attributes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.api.alerts import router as alerts_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.deps import get_auth_settings  # noqa: E402
from app.api.devices import router as devices_router  # noqa: E402
from app.api.system import router as system_router  # noqa: E402
from app.api.users import router as users_router  # noqa: E402
from app.core.config import AuthSettings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Alert, Base, Device, SensorReading, User  # noqa: E402
from app.models.enums import AlertSeverity, AlertType, UserRole  # noqa: E402
from app.schemas.contracts import Attribution, TrustScores  # noqa: E402
from app.schemas.decision_diagnostic import (  # noqa: E402
    ChannelAttribution,
    DecisionDiagnosticMessage,
)
from app.services.decision_diagnostic_persistence import DecisionDiagnosticPersistence  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

TEST_SETTINGS = AuthSettings(
    jwt_secret_key="unit-test-secret",
    jwt_access_ttl_min=15,
    jwt_refresh_ttl_days=7,
    password_bcrypt_rounds=4,
)


class _FakeConsumer:
    def is_connected(self) -> bool:
        return True


class _FakeBroadcaster:
    client_count = 2


class _FakeStore:
    count = 7


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def client(session_factory):
    app = FastAPI()
    for router in (auth_router, devices_router, alerts_router, users_router, system_router):
        app.include_router(router)
    app.state.telemetry_consumer = _FakeConsumer()
    app.state.telemetry_broadcaster = _FakeBroadcaster()
    app.state.telemetry_store = _FakeStore()

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_settings] = lambda: TEST_SETTINGS
    return TestClient(app)


@pytest.fixture()
def seed(session_factory):
    """admin / operator / analyst users; pump-01 owned by operator, pump-02
    unowned; one reading on pump-01; one open alert on pump-01."""
    with session_factory() as db:
        admin = User(
            email="admin@example.com",
            password_hash=hash_password("adminpw", TEST_SETTINGS),
            role=UserRole.admin,
        )
        operator = User(
            email="operator@example.com",
            password_hash=hash_password("oppw", TEST_SETTINGS),
            role=UserRole.operator,
        )
        analyst = User(
            email="analyst@example.com",
            password_hash=hash_password("anpw", TEST_SETTINGS),
            role=UserRole.analyst,
        )
        db.add_all([admin, operator, analyst])
        db.commit()
        db.refresh(operator)

        pump01 = Device(device_id="pump-01", name="Pump 01", owner_user_id=operator.id)
        pump02 = Device(device_id="pump-02", name="Pump 02")
        db.add_all([pump01, pump02])
        db.commit()
        db.refresh(pump01)

        db.add(
            SensorReading(
                device_id=pump01.id,
                ts=datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC),
                sample_seq=0,
                temperature=26.0,
                vibration=0.03,
                pressure=1013.0,
                humidity=45.0,
                gas=150.0,
                current=0.0,
                healthy_mask=0b111111,
            )
        )
        db.add(
            Alert(
                device_id=pump01.id,
                ts=datetime.now(UTC),
                severity=AlertSeverity.warning,
                type=AlertType.fault,
                message="vibration trending up",
            )
        )
        db.commit()
    return {"pump01_owner": "operator@example.com"}


def _login(client, email, password) -> str:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin_token(client) -> str:
    return _login(client, "admin@example.com", "adminpw")


def _operator_token(client) -> str:
    return _login(client, "operator@example.com", "oppw")


def _analyst_token(client) -> str:
    return _login(client, "analyst@example.com", "anpw")


# ---- devices ---------------------------------------------------------------


def test_admin_lists_all_devices(client, seed):
    r = client.get("/api/devices", headers=_auth(_admin_token(client)))
    assert r.status_code == 200
    assert {d["device_id"] for d in r.json()} == {"pump-01", "pump-02"}


def test_operator_lists_only_owned_devices(client, seed):
    r = client.get("/api/devices", headers=_auth(_operator_token(client)))
    assert r.status_code == 200
    assert [d["device_id"] for d in r.json()] == ["pump-01"]


def test_analyst_with_no_owned_devices_sees_empty_list(client, seed):
    r = client.get("/api/devices", headers=_auth(_analyst_token(client)))
    assert r.status_code == 200
    assert r.json() == []


def test_operator_can_get_owned_device(client, seed):
    r = client.get("/api/devices/pump-01", headers=_auth(_operator_token(client)))
    assert r.status_code == 200
    assert r.json()["device_id"] == "pump-01"


def test_operator_cannot_get_unowned_device_404_not_403(client, seed):
    r = client.get("/api/devices/pump-02", headers=_auth(_operator_token(client)))
    assert r.status_code == 404


def test_get_unknown_device_is_404(client, seed):
    r = client.get("/api/devices/does-not-exist", headers=_auth(_admin_token(client)))
    assert r.status_code == 404


def test_admin_creates_device(client, seed):
    r = client.post(
        "/api/devices",
        json={"device_id": "pump-03", "name": "Pump 03"},
        headers=_auth(_admin_token(client)),
    )
    assert r.status_code == 201
    assert r.json()["device_id"] == "pump-03"


def test_non_admin_cannot_create_device(client, seed):
    r = client.post(
        "/api/devices",
        json={"device_id": "pump-99", "name": "X"},
        headers=_auth(_operator_token(client)),
    )
    assert r.status_code == 403


def test_create_device_duplicate_id_is_409(client, seed):
    r = client.post(
        "/api/devices",
        json={"device_id": "pump-01", "name": "dup"},
        headers=_auth(_admin_token(client)),
    )
    assert r.status_code == 409


def test_admin_updates_device_name(client, seed):
    r = client.patch(
        "/api/devices/pump-01",
        json={"name": "Renamed Pump"},
        headers=_auth(_admin_token(client)),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Pump"


def test_non_admin_cannot_update_device(client, seed):
    r = client.patch(
        "/api/devices/pump-01",
        json={"name": "hacked"},
        headers=_auth(_operator_token(client)),
    )
    assert r.status_code == 403


def test_get_readings_returns_rows_in_range(client, seed):
    r = client.get(
        "/api/devices/pump-01/readings",
        params={"from": "2026-09-05T00:00:00Z", "to": "2026-09-06T00:00:00Z"},
        headers=_auth(_operator_token(client)),
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["temperature"] == 26.0


def test_get_readings_out_of_range_is_empty(client, seed):
    r = client.get(
        "/api/devices/pump-01/readings",
        params={"from": "2020-01-01T00:00:00Z", "to": "2020-01-02T00:00:00Z"},
        headers=_auth(_operator_token(client)),
    )
    assert r.status_code == 200
    assert r.json() == []


def test_get_readings_unsupported_agg_is_400(client, seed):
    r = client.get(
        "/api/devices/pump-01/readings",
        params={"agg": "1min"},
        headers=_auth(_operator_token(client)),
    )
    assert r.status_code == 400


def test_get_decisions_empty_is_honest_not_fabricated(client, seed):
    r = client.get("/api/devices/pump-01/decisions", headers=_auth(_operator_token(client)))
    assert r.status_code == 200
    assert r.json() == []


def test_get_decisions_returns_partial_diagnostic_row(client, seed, session_factory):
    """A decision_diagnostic message ingested via the real
    DecisionDiagnosticPersistence sink must appear over this pre-existing
    REST endpoint with zero endpoint-code changes -- proving the milestone's
    'REST needs no new code' claim, not just asserting it."""
    message = DecisionDiagnosticMessage(
        device_id="pump-01",
        ts="2026-09-06T12:00:00.000Z",
        sample_seq=42,
        window_start_index=0,
        window_end_index=30,
        anomaly_flag=True,
        anomaly_severity=0.66,
        trust=TrustScores(
            temperature=0.9, vibration=0.2, pressure=0.9, humidity=0.9, gas=0.9, current=0.9
        ),
        attribution={
            "temperature": ChannelAttribution(attribution=Attribution.none, reason=""),
            "vibration": ChannelAttribution(attribution=Attribution.fault, reason="anomaly"),
            "pressure": ChannelAttribution(attribution=Attribution.none, reason=""),
            "humidity": ChannelAttribution(attribution=Attribution.none, reason=""),
            "gas": ChannelAttribution(attribution=Attribution.none, reason=""),
            "current": ChannelAttribution(attribution=Attribution.none, reason=""),
        },
        isolation_candidates=[],
        tracked_isolation_candidates=[],
    )
    DecisionDiagnosticPersistence(session_factory).persist(message)

    r = client.get("/api/devices/pump-01/decisions", headers=_auth(_operator_token(client)))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["anomaly_flag"] is True
    assert row["anomaly_severity"] == 0.66
    # Fields this diagnostic payload cannot honestly populate stay NULL --
    # never a fabricated health/action/isolation/attribution claim.
    assert row["health_state"] is None
    assert row["failure_eta"] is None
    assert row["rl_action"] is None
    assert row["isolated_channels"] is None
    assert row["substituted_channels"] is None
    assert row["attribution"] is None
    assert row["reason"] is None


def test_get_thresholds_lazily_creates_defaults(client, seed):
    r = client.get("/api/devices/pump-01/thresholds", headers=_auth(_admin_token(client)))
    assert r.status_code == 200
    body = r.json()
    assert body["trust_trusted_min"] == 0.7
    assert body["substitution_max_seconds"] == 60
    assert body["divergence_threshold"] is None  # U05 — never silently defaulted


def test_non_admin_cannot_read_thresholds(client, seed):
    r = client.get("/api/devices/pump-01/thresholds", headers=_auth(_operator_token(client)))
    assert r.status_code == 403


def test_admin_updates_thresholds_and_stamps_audit_fields(client, seed):
    token = _admin_token(client)
    r = client.patch(
        "/api/devices/pump-01/thresholds",
        json={"divergence_threshold": 2.5},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["divergence_threshold"] == 2.5
    assert body["updated_at"] is not None
    assert body["updated_by"] is not None


# ---- alerts ------------------------------------------------------------


def test_operator_lists_own_alerts_only(client, seed):
    r = client.get("/api/alerts", headers=_auth(_operator_token(client)))
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["device_id"] == "pump-01"


def test_analyst_with_no_devices_sees_no_alerts(client, seed):
    r = client.get("/api/alerts", headers=_auth(_analyst_token(client)))
    assert r.status_code == 200
    assert r.json() == []


def test_alerts_filter_by_unowned_device_is_empty_not_error(client, seed):
    r = client.get(
        "/api/alerts", params={"device": "pump-02"}, headers=_auth(_operator_token(client))
    )
    assert r.status_code == 200
    assert r.json() == []


def test_alerts_invalid_status_filter_is_400(client, seed):
    r = client.get(
        "/api/alerts", params={"status": "bogus"}, headers=_auth(_operator_token(client))
    )
    assert r.status_code == 400


def test_alerts_status_open_filter(client, seed):
    r = client.get(
        "/api/alerts", params={"status": "open"}, headers=_auth(_operator_token(client))
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_ack_alert_sets_fields(client, seed):
    token = _operator_token(client)
    listing = client.get("/api/alerts", headers=_auth(token)).json()
    alert_id = listing[0]["id"]

    r = client.post(f"/api/alerts/{alert_id}/ack", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["acknowledged_at"] is not None
    assert r.json()["acknowledged_by"] is not None

    r2 = client.get("/api/alerts", params={"status": "open"}, headers=_auth(token))
    assert r2.json() == []


def test_ack_unknown_alert_is_404(client, seed):
    r = client.post(
        "/api/alerts/11111111-1111-1111-1111-111111111111/ack",
        headers=_auth(_operator_token(client)),
    )
    assert r.status_code == 404


def test_ack_alert_malformed_id_is_404_not_500(client, seed):
    r = client.post("/api/alerts/not-a-uuid/ack", headers=_auth(_operator_token(client)))
    assert r.status_code == 404


def test_analyst_cannot_ack_alert_on_unowned_device(client, seed):
    token = _operator_token(client)
    listing = client.get("/api/alerts", headers=_auth(token)).json()
    alert_id = listing[0]["id"]

    r = client.post(f"/api/alerts/{alert_id}/ack", headers=_auth(_analyst_token(client)))
    assert r.status_code == 404


# ---- users ---------------------------------------------------------------


def test_admin_lists_users(client, seed):
    r = client.get("/api/users", headers=_auth(_admin_token(client)))
    assert r.status_code == 200
    assert {u["email"] for u in r.json()} == {
        "admin@example.com",
        "operator@example.com",
        "analyst@example.com",
    }


def test_non_admin_cannot_list_users(client, seed):
    r = client.get("/api/users", headers=_auth(_operator_token(client)))
    assert r.status_code == 403


def test_admin_creates_user(client, seed):
    r = client.post(
        "/api/users",
        json={"email": "new@example.com", "password": "x", "role": "operator"},
        headers=_auth(_admin_token(client)),
    )
    assert r.status_code == 201
    assert r.json()["role"] == "operator"


def test_create_user_duplicate_email_is_409(client, seed):
    r = client.post(
        "/api/users",
        json={"email": "operator@example.com", "password": "x", "role": "analyst"},
        headers=_auth(_admin_token(client)),
    )
    assert r.status_code == 409


def test_admin_updates_user_role(client, seed):
    token = _admin_token(client)
    users = client.get("/api/users", headers=_auth(token)).json()
    analyst_id = next(u["id"] for u in users if u["email"] == "analyst@example.com")

    r = client.patch(
        f"/api/users/{analyst_id}", json={"is_active": False}, headers=_auth(token)
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_non_admin_cannot_update_user(client, seed):
    token = _operator_token(client)
    users_as_admin = client.get("/api/users", headers=_auth(_admin_token(client))).json()
    target_id = users_as_admin[0]["id"]

    r = client.patch(f"/api/users/{target_id}", json={"is_active": False}, headers=_auth(token))
    assert r.status_code == 403


# ---- system health ---------------------------------------------------------


def test_admin_reads_system_health(client, seed):
    r = client.get("/api/system/health", headers=_auth(_admin_token(client)))
    assert r.status_code == 200
    body = r.json()
    assert body["mqtt_connected"] is True
    assert body["db_connected"] is True
    assert body["ws_clients"] == 2
    assert body["telemetry_count"] == 7
    assert body["e2e_latency_ms"] is None  # never fabricated


def test_non_admin_cannot_read_system_health(client, seed):
    r = client.get("/api/system/health", headers=_auth(_operator_token(client)))
    assert r.status_code == 403
