"""Pre-flight self-check (scripts/preflight.py; PRD §18.3, AC10 P8-2/P8-6).

The pure checks are tested directly; the whole script is also run against the
real REST routers (SQLite, TestClient as its HTTP opener) so a renamed endpoint
or a changed response shape fails here, not at T-15 minutes."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("jose")
pytest.importorskip("passlib")

from app.api.auth import router as auth_router  # noqa: E402
from app.api.deps import get_auth_settings  # noqa: E402
from app.api.devices import router as devices_router  # noqa: E402
from app.api.ledger import router as ledger_router  # noqa: E402
from app.api.system import router as system_router  # noqa: E402
from app.core.config import AuthSettings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Base, Decision, Device, SensorReading, User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.services.latency_tracker import LatencyTracker  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "preflight.py"
_spec = importlib.util.spec_from_file_location("preflight", _SCRIPT)
preflight = importlib.util.module_from_spec(_spec)
sys.modules["preflight"] = preflight  # dataclasses resolve their module by name
_spec.loader.exec_module(preflight)

SETTINGS = AuthSettings(
    jwt_secret_key="unit-test-secret",
    jwt_access_ttl_min=15,
    jwt_refresh_ttl_days=7,
    password_bcrypt_rounds=4,
)
NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)


def _reading(i: int, **overrides) -> dict:
    row = {ch: 1.0 for ch in preflight.CHANNELS}
    row["ts"] = (NOW - timedelta(seconds=29 - i)).isoformat()
    row.update(overrides)
    return row


# --- pure checks ---------------------------------------------------------------


def test_healthy_system_passes():
    checks = preflight.check_system_health(
        {"mqtt_connected": True, "db_connected": True, "e2e_latency_ms": 180.0}
    )
    assert [c.status for c in checks] == ["PASS", "PASS", "PASS"]


def test_broker_down_is_named():
    (mqtt, *_) = preflight.check_system_health(
        {"mqtt_connected": False, "db_connected": True, "e2e_latency_ms": 100.0}
    )
    assert mqtt.status == "FAIL" and "mosquitto" in mqtt.detail


@pytest.mark.parametrize(
    "latency, status",
    [(500.0, "PASS"), (1500.0, "WARN"), (2500.0, "FAIL"), (None, "FAIL")],
)
def test_latency_bands(latency, status):
    checks = preflight.check_system_health(
        {"mqtt_connected": True, "db_connected": True, "e2e_latency_ms": latency}
    )
    assert checks[-1].status == status


def test_live_telemetry_at_1hz_with_six_channels_passes():
    checks = preflight.check_telemetry([_reading(i) for i in range(30)], NOW)
    assert [c.status for c in checks] == ["PASS", "PASS", "PASS"]


def test_stale_telemetry_fails_and_hints_at_the_edge():
    checks = preflight.check_telemetry([_reading(i) for i in range(30)], NOW + timedelta(minutes=2))
    assert checks[0].status == "FAIL" and "edge" in checks[0].detail


def test_no_telemetry_fails():
    assert preflight.check_telemetry([], NOW)[0].status == "FAIL"


def test_missing_channel_fails():
    rows = [_reading(i) for i in range(29)] + [_reading(29, gas=None)]
    assert preflight.check_telemetry(rows, NOW)[-1].status == "FAIL"


def test_broken_ledger_names_the_block():
    check = preflight.check_ledger({"valid": False, "broken_at": 7})
    assert check.status == "FAIL" and "7" in check.detail


def test_trust_bands():
    green = {f"trust_{ch}": 0.9 for ch in preflight.CHANNELS} | {"isolated_channels": []}
    assert preflight.check_trust([green]).status == "PASS"
    assert preflight.check_trust([green | {"trust_current": 0.5}]).status == "WARN"
    assert preflight.check_trust([green | {"isolated_channels": ["current"]}]).status == "FAIL"
    assert preflight.check_trust([]).status == "FAIL"


def test_replay_file(tmp_path):
    path = tmp_path / "session.jsonl"
    path.write_text(json.dumps({"sensors": {"current": 0.0}}) + "\nnoise\n", encoding="utf-8")
    assert preflight.check_replay_file(path).status == "PASS"
    assert preflight.check_replay_file(tmp_path / "absent.jsonl").status == "FAIL"
    empty = tmp_path / "empty.jsonl"
    empty.write_text("noise\n", encoding="utf-8")
    assert preflight.check_replay_file(empty).status == "FAIL"


# --- the whole script against the real routers -----------------------------------


@pytest.fixture()
def api():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    for router in (auth_router, devices_router, system_router, ledger_router):
        app.include_router(router)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    app.state.telemetry_consumer = SimpleNamespace(is_connected=lambda: True)
    app.state.telemetry_broadcaster = SimpleNamespace(client_count=1)
    app.state.telemetry_store = SimpleNamespace(count=30)
    tracker = LatencyTracker()
    app.state.latency_tracker = tracker

    def _get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_settings] = lambda: SETTINGS
    now = datetime.now(UTC)
    with factory() as db:
        db.add(
            User(
                email="admin@example.com",
                password_hash=hash_password("adminpw", SETTINGS),
                role=UserRole.admin,
            )
        )
        device = Device(device_id="pump-01", name="Pump 01")
        db.add(device)
        db.commit()
        db.refresh(device)
        for i in range(30):
            db.add(
                SensorReading(
                    device_id=device.id,
                    ts=now - timedelta(seconds=29 - i),
                    sample_seq=i,
                    temperature=26.0,
                    vibration=0.1,
                    pressure=916.0,
                    humidity=45.0,
                    gas=150.0,
                    current=0.0,
                    healthy_mask=0b111111,
                )
            )
        db.add(
            Decision(
                device_id=device.id,
                ts=now,
                **{f"trust_{ch}": 0.9 for ch in preflight.CHANNELS},
                isolated_channels=[],
            )
        )
        db.commit()
    return TestClient(app), tracker


def _opener(client: TestClient):
    """urllib-shaped opener backed by the in-process TestClient."""

    def _open(request, timeout=None):
        url = request.full_url.replace("http://preflight.test", "")
        headers = {k: v for k, v in request.header_items()}
        response = client.request(request.get_method(), url, content=request.data, headers=headers)
        if response.status_code >= 400:
            raise preflight.urllib.error.HTTPError(
                url, response.status_code, response.text, None, None
            )
        return io.BytesIO(response.content)

    return _open


def _args(**overrides):
    values = {"backend": "http://preflight.test", "device": "pump-01", "replay_file": None}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_script_passes_against_the_real_routes_when_latency_is_measured(api):
    client, tracker = api
    sent = datetime.now(UTC) - timedelta(milliseconds=200)
    tracker.record(sent.isoformat().replace("+00:00", "Z"))
    backend = preflight.Backend("http://preflight.test", opener=_opener(client))
    env = {"SHTAPM_PREFLIGHT_EMAIL": "admin@example.com", "SHTAPM_PREFLIGHT_PASSWORD": "adminpw"}
    checks = {c.name: c for c in preflight.run(_args(), backend, env)}
    for name in ("backend", "login", "MQTT broker", "database", "telemetry live", "six channels"):
        assert checks[name].status == "PASS", (name, checks[name].detail)
    assert checks["ledger"].status == "PASS"
    assert checks["trust baseline"].status == "PASS"
    assert checks["relay"].status == "MANUAL"
    assert checks["fallback armed"].status == "SKIP"


def test_script_without_credentials_names_the_variables(api):
    client, _ = api
    backend = preflight.Backend("http://preflight.test", opener=_opener(client))
    checks = preflight.run(_args(), backend, {})
    assert checks[-1].status == "FAIL" and "SHTAPM_PREFLIGHT_EMAIL" in checks[-1].detail


def test_script_with_wrong_password_fails_at_login(api):
    client, _ = api
    backend = preflight.Backend("http://preflight.test", opener=_opener(client))
    env = {"SHTAPM_PREFLIGHT_EMAIL": "admin@example.com", "SHTAPM_PREFLIGHT_PASSWORD": "nope"}
    checks = preflight.run(_args(), backend, env)
    assert checks[-1].name == "login" and checks[-1].status == "FAIL"


def test_unreachable_backend_is_named():
    def _refuse(request, timeout=None):
        raise preflight.urllib.error.URLError("connection refused")

    backend = preflight.Backend("http://nowhere.test", opener=_refuse)
    checks = preflight.run(_args(backend="http://nowhere.test"), backend, {})
    assert checks == [checks[0]] and checks[0].status == "FAIL"
    assert "nowhere.test" in checks[0].detail
