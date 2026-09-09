"""CORS configuration + middleware behaviour.

Why this matters here specifically: the SHTAPM dashboard is served from Vite on
:5173 while the API is published on :8002, so EVERY browser call is
cross-origin. A blocked CORS request rejects `fetch` with a TypeError rather
than an HTTP status, so in the UI it is indistinguishable from "the backend is
down" — which is exactly how it presented on the Pi. These tests pin the
behaviour so that failure mode cannot come back silently.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from app.core.config import CorsSettings  # noqa: E402
from app.main import configure_cors  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PI_ORIGIN = "http://192.168.1.20:5173"
LOCAL_ORIGIN = "http://localhost:5173"


def _client(origins: tuple[str, ...]) -> TestClient:
    app = FastAPI()

    @app.get("/probe")
    def probe() -> dict:
        return {"ok": True}

    configure_cors(app, CorsSettings(allowed_origins=origins))
    return TestClient(app)


# ---------------------------------------------------------------------------
# CorsSettings parsing
# ---------------------------------------------------------------------------


def test_defaults_to_the_documented_localhost_origin_when_unset():
    assert CorsSettings.from_env(env={}).allowed_origins == (LOCAL_ORIGIN,)


def test_parses_a_comma_separated_list():
    settings = CorsSettings.from_env(env={"CORS_ALLOWED_ORIGINS": f"{LOCAL_ORIGIN},{PI_ORIGIN}"})
    assert settings.allowed_origins == (LOCAL_ORIGIN, PI_ORIGIN)


def test_tolerates_whitespace_and_empty_entries():
    settings = CorsSettings.from_env(
        env={"CORS_ALLOWED_ORIGINS": f" {LOCAL_ORIGIN} , , {PI_ORIGIN} "}
    )
    assert settings.allowed_origins == (LOCAL_ORIGIN, PI_ORIGIN)


def test_an_explicitly_empty_value_allows_no_origin():
    """Empty means "allow nothing", NOT "fall back to the default" — an
    operator who blanks the variable must not silently get localhost back."""
    assert CorsSettings.from_env(env={"CORS_ALLOWED_ORIGINS": ""}).allowed_origins == ()


def test_wildcard_is_supported_but_never_the_default():
    assert CorsSettings.from_env(env={"CORS_ALLOWED_ORIGINS": "*"}).allowed_origins == ("*",)
    assert "*" not in CorsSettings.from_env(env={}).allowed_origins


# ---------------------------------------------------------------------------
# Middleware behaviour
# ---------------------------------------------------------------------------


def test_allowed_origin_gets_the_cors_header_on_a_simple_request():
    client = _client((PI_ORIGIN,))
    response = client.get("/probe", headers={"Origin": PI_ORIGIN})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PI_ORIGIN


def test_preflight_from_an_allowed_origin_succeeds():
    """The login POST sends Content-Type: application/json, which makes it a
    preflighted request — so OPTIONS must be answered, not just the POST."""
    client = _client((PI_ORIGIN,))
    response = client.options(
        "/probe",
        headers={
            "Origin": PI_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PI_ORIGIN


def test_authorization_header_is_permitted_by_preflight():
    """Every authenticated call sends Authorization: Bearer <jwt>."""
    client = _client((PI_ORIGIN,))
    response = client.options(
        "/probe",
        headers={
            "Origin": PI_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed or allowed == "*"


def test_disallowed_origin_gets_no_cors_header():
    """The browser blocks on the header's ABSENCE — the response body still
    arrives, so asserting the status code alone would prove nothing."""
    client = _client((LOCAL_ORIGIN,))
    response = client.get("/probe", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_multiple_origins_are_each_echoed_back():
    client = _client((LOCAL_ORIGIN, PI_ORIGIN))
    for origin in (LOCAL_ORIGIN, PI_ORIGIN):
        response = client.get("/probe", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin


def test_same_origin_requests_are_unaffected():
    """No Origin header (curl, health checks) must behave exactly as before."""
    client = _client((PI_ORIGIN,))
    response = client.get("/probe")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_credentials_are_not_enabled():
    """Bearer tokens travel in a header, not cookies. Enabling credentialed
    CORS would also make a "*" origin list illegal per the CORS spec."""
    client = _client((PI_ORIGIN,))
    response = client.get("/probe", headers={"Origin": PI_ORIGIN})
    assert "access-control-allow-credentials" not in response.headers
