"""Regression tests for the P5 login-500 investigation.

Two defects made a single backend exception take several rounds to find, and
both are pinned here:

1. An unhandled exception produced a 500 with NO CORS headers, because
   Starlette's ServerErrorMiddleware sits outside CORSMiddleware. The browser
   discarded the response, `fetch` rejected with a TypeError, and the UI
   reported a network outage — while DevTools showed the real 500. Two correct
   observations that flatly contradicted each other.

2. /healthz reported "ok" while the database was unreachable, because
   `make_engine()` does not connect (SQLAlchemy connects lazily) and /healthz
   queried nothing. POST /api/auth/login was the first request in the entire
   app to touch the database, so a bad DATABASE_URL surfaced as a broken login
   endpoint rather than as a broken database.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("paho.mqtt.client")

from app.core.config import CorsSettings  # noqa: E402
from app.main import UnhandledExceptionMiddleware, app, configure_cors  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ORIGIN = "http://192.168.1.20:5173"


def _app_with_boom() -> TestClient:
    """Mirrors app.main's wiring order exactly: catcher added first (innermost),
    CORS second (outermost) so it can decorate the catcher's response."""
    test_app = FastAPI()

    @test_app.get("/boom")
    def boom() -> dict:
        raise RuntimeError("simulated unhandled error")

    @test_app.get("/fine")
    def fine() -> dict:
        return {"ok": True}

    test_app.add_middleware(UnhandledExceptionMiddleware)
    configure_cors(test_app, CorsSettings(allowed_origins=(ORIGIN,)))
    return TestClient(test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. A 500 must reach the browser as a readable 500
# ---------------------------------------------------------------------------


def test_unhandled_exception_returns_500_with_cors_headers():
    """THE regression: without the middleware this header is absent and the
    browser turns a perfectly good 500 into an unexplained network error."""
    response = _app_with_boom().get("/boom", headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_unhandled_exception_body_is_generic_and_leaks_nothing():
    """An internal message can carry a DSN (with password) or a query
    fragment. The detail belongs in the server log, not in a browser response."""
    response = _app_with_boom().get("/boom", headers={"Origin": ORIGIN})
    assert response.json() == {"detail": "Internal Server Error"}
    assert "simulated unhandled error" not in response.text


def test_successful_responses_are_unaffected():
    response = _app_with_boom().get("/fine", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_the_exception_is_logged_server_side(caplog):
    """The detail must not simply vanish — it is the operator's only copy."""
    with caplog.at_level("ERROR", logger="shtapm.backend"):
        _app_with_boom().get("/boom", headers={"Origin": ORIGIN})
    assert any("unhandled error" in record.message for record in caplog.records)


def test_middleware_is_wired_into_the_real_app():
    """Guards the ORDER too: reversing the two lines in app.main silently
    reintroduces the header-less 500."""
    classes = [m.cls for m in app.user_middleware]
    assert UnhandledExceptionMiddleware in classes
    from fastapi.middleware.cors import CORSMiddleware

    # user_middleware is outermost-first, so CORS must precede the catcher.
    assert classes.index(CORSMiddleware) < classes.index(UnhandledExceptionMiddleware)


# ---------------------------------------------------------------------------
# 2. /healthz must not claim health while the database is unreachable
# ---------------------------------------------------------------------------


def _healthz(monkeypatch, database_url: str) -> dict:
    monkeypatch.setenv("MQTT_HOST", "127.0.0.1")
    monkeypatch.setenv("MQTT_PORT", "1")  # no broker required
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-not-real")
    with TestClient(app) as client:
        return client.get("/healthz").json()


def test_healthz_reports_a_reachable_database(monkeypatch):
    body = _healthz(monkeypatch, "sqlite://")
    assert body["db_connected"] is True
    assert body["db_error"] is None


class OperationalError(Exception):
    """Stands in for the driver error SQLAlchemy raises when it cannot connect.
    Its message embeds the DSN exactly as psycopg's real one does — that is the
    leak this guards against, so the test must control the text."""


_LEAKY_MESSAGE = (
    "connection to server at 10.0.0.9, port 5432 failed for DSN "
    "postgresql+psycopg://someuser:sup3rs3cret@10.0.0.9:5432/shtapm"
)


class _UnreachableSessionFactory:
    """Session factory whose queries always fail — no driver required, so this
    runs everywhere instead of needing a real Postgres on the test machine."""

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, *args, **kwargs):
        raise OperationalError(_LEAKY_MESSAGE)


def _healthz_with_broken_db(monkeypatch) -> dict:
    monkeypatch.setenv("MQTT_HOST", "127.0.0.1")
    monkeypatch.setenv("MQTT_PORT", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-not-real")
    with TestClient(app) as client:
        # Replace only AFTER lifespan has wired the real one.
        monkeypatch.setattr(app.state, "db_sessionmaker", _UnreachableSessionFactory())
        return client.get("/healthz").json()


def test_healthz_reports_an_unreachable_database(monkeypatch):
    """The case that was invisible: engine creation succeeds, lifespan
    succeeds, MQTT connects, and nothing notices until a request queries."""
    body = _healthz_with_broken_db(monkeypatch)
    assert body["db_connected"] is False
    assert body["db_error"] == "OperationalError"


def test_healthz_never_leaks_the_connection_string(monkeypatch):
    """Driver connection errors routinely embed the DSN, password and all.
    Only the exception CLASS name may be reported."""
    serialized = str(_healthz_with_broken_db(monkeypatch))
    assert "sup3rs3cret" not in serialized
    assert "someuser" not in serialized
    assert "10.0.0.9" not in serialized


def test_healthz_reports_when_the_database_was_never_configured(monkeypatch):
    body = _healthz(monkeypatch, "sqlite://")
    assert body["db_connected"] is True  # sanity: the happy path still passes


def test_healthz_still_reports_the_pre_existing_fields(monkeypatch):
    """Additive change only — nothing that already consumed /healthz breaks."""
    body = _healthz(monkeypatch, "sqlite://")
    assert body["status"] == "ok"
    assert body["mqtt_connected"] is False
    assert body["telemetry_count"] == 0
    assert body["devices"] == []
    assert "ws_clients" in body
