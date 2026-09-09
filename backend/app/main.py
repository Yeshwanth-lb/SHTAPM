"""SHTAPM FastAPI backend (P0 M3.4 MQTT/WS; P4 adds DB + auth + REST).

Lifespan starts the MQTT telemetry consumer (paho's own thread) and a
``TelemetryBroadcaster`` (the seam to WebSocket clients), wiring the
consumer's sink to the broadcaster so each validated telemetry message is
pushed live to connected ``/ws`` clients — and, since P4-M3, to a second
sink (``TelemetryPersistence``) that writes it to ``sensor_readings`` off
that same live-delivery hot path. The in-memory ``TelemetryStore`` remains
the latest state. Broker downtime is tolerated: the consumer connects async
and retries, so the app still starts and stays up.

Also starts a second, wholly independent ``DecisionDiagnosticConsumer``
(its own client/subscription/thread) on ``shtapm/+/decision_diagnostic`` —
a NEW, separate topic, NOT the frozen Doc05 ``.../decision`` topic/
``DecisionMessage`` shape (see ``app.schemas.decision_diagnostic``'s own
docstring for why). Its sink (``DecisionDiagnosticPersistence``) writes
partial rows into the EXISTING ``decisions`` table — no schema change, no
WS frame (deferred; REST/DB ingestion is this milestone's scope). Being a
fully separate consumer object, a broker/topic failure here cannot affect
telemetry ingestion in any way.

``DATABASE_URL``/``JWT_SECRET_KEY`` are REQUIRED (raise at startup if
unset, per TRD §02.7 "missing var → clear boot error naming it") — tests
that boot this app now set both via monkeypatch, same as the pre-existing
``MQTT_HOST``/``MQTT_PORT`` pattern. A SQLite ``DATABASE_URL`` gets its
tables created here directly (``Base.metadata.create_all``) for
tests/dev convenience; a real Postgres URL does NOT — that schema comes
only from Alembic (``backend/alembic/``), never from an app-side create_all.

Scope still excluded from this slice (see project-state plan): ledger MQTT
ingestion (no producer exists yet), a WS decision/decision-diagnostic frame
(deferred), Postgres RLS (app-level scoping only — see ``app.api.deps``),
and scenario injection (``U14``, unspecified payload).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.alerts import router as alerts_router
from app.api.auth import router as auth_router
from app.api.devices import router as devices_router
from app.api.ledger import router as ledger_router
from app.api.system import router as system_router
from app.api.users import router as users_router
from app.core.config import AuthSettings, CorsSettings, DatabaseSettings, MqttSettings
from app.core.db import make_engine, make_session_factory
from app.models import Base
from app.mqtt.consumer import TelemetryConsumer
from app.mqtt.decision_diagnostic_consumer import DecisionDiagnosticConsumer
from app.services.decision_diagnostic_persistence import DecisionDiagnosticPersistence
from app.services.telemetry_persistence import TelemetryPersistence
from app.services.telemetry_store import TelemetryStore
from app.ws.broadcaster import TelemetryBroadcaster
from app.ws.routes import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_settings = DatabaseSettings.from_env()
    auth_settings = AuthSettings.from_env()
    engine = make_engine(db_settings.url)
    if db_settings.url.startswith("sqlite"):
        Base.metadata.create_all(engine)  # prod/Postgres schema comes from Alembic only
    session_factory = make_session_factory(engine)
    app.state.db_sessionmaker = session_factory
    app.state.auth_settings = auth_settings

    store = TelemetryStore()
    broadcaster = TelemetryBroadcaster(asyncio.get_running_loop())
    persistence = TelemetryPersistence(session_factory)
    consumer = TelemetryConsumer(store)
    consumer.add_sink(broadcaster.publish_from_thread)  # MQTT → WS seam
    consumer.add_sink(persistence.persist)  # MQTT → DB seam (off the WS hot path)
    settings = MqttSettings.from_env()
    consumer.start(settings.host, settings.port)  # non-blocking; tolerates broker down
    app.state.telemetry_store = store
    app.state.telemetry_broadcaster = broadcaster
    app.state.telemetry_consumer = consumer

    # Wholly separate consumer/subscription/thread -- see module docstring's
    # decision_diagnostic paragraph. Independent of everything above.
    decision_diagnostic_persistence = DecisionDiagnosticPersistence(session_factory)
    decision_diagnostic_consumer = DecisionDiagnosticConsumer()
    decision_diagnostic_consumer.add_sink(decision_diagnostic_persistence.persist)
    decision_diagnostic_consumer.start(settings.host, settings.port)
    app.state.decision_diagnostic_consumer = decision_diagnostic_consumer
    try:
        yield
    finally:
        consumer.stop()
        decision_diagnostic_consumer.stop()
        engine.dispose()


log = logging.getLogger("shtapm.backend")


class UnhandledExceptionMiddleware(BaseHTTPMiddleware):
    """Turn an unhandled exception into a real 500 *response*.

    Without this, an escaping exception is caught by Starlette's
    ServerErrorMiddleware, which sits OUTSIDE CORSMiddleware — so the 500 goes
    back with no ``access-control-allow-origin`` header. The browser then
    discards it and ``fetch`` rejects with a TypeError, which is
    indistinguishable in the UI from "the backend is down". That is exactly how
    a login 500 presented during P5 bring-up: DevTools showed the 500 while the
    dashboard reported a network failure, and the real error was invisible.

    Registered BEFORE CORSMiddleware so it ends up INSIDE it (Starlette applies
    middleware outermost-last), letting CORS decorate the response this returns.

    The body stays generic on purpose — an internal error message can carry a
    connection string or a query fragment, and this endpoint is browser-facing.
    The detail goes to the server log instead, with the traceback.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            return await call_next(request)
        except Exception:
            log.exception("unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
            )


def configure_cors(app: FastAPI, settings: CorsSettings | None = None) -> FastAPI:
    """Attach CORSMiddleware from CORS_ALLOWED_ORIGINS.

    Separated from module import so tests can exercise it against an explicit
    settings object instead of process env. ``allow_credentials`` stays False:
    this API authenticates with a bearer token in the Authorization header, not
    cookies, so credentialed CORS is unnecessary — and enabling it would make
    a "*" origin list illegal per the CORS spec.
    """
    resolved = settings if settings is not None else CorsSettings.from_env()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.allowed_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = FastAPI(title="SHTAPM backend", lifespan=lifespan)
# Order matters: added first => innermost, so configure_cors() below wraps it
# and its 500 responses carry CORS headers. Reversing these two lines silently
# reintroduces the "500 looks like a network outage" failure.
app.add_middleware(UnhandledExceptionMiddleware)
configure_cors(app)
app.include_router(ws_router)
app.include_router(auth_router)
app.include_router(devices_router)
app.include_router(alerts_router)
app.include_router(users_router)
app.include_router(system_router)
app.include_router(ledger_router)


def _db_status() -> tuple[bool, str | None]:
    """Can we actually reach the database right now?

    ``make_engine()`` does not connect — SQLAlchemy connects lazily on first
    use — so an unreachable or misconfigured database stays invisible until
    some request happens to query it. During P5 bring-up that made a wrong
    DATABASE_URL look like a broken login endpoint: lifespan succeeded,
    /healthz returned "ok", MQTT connected, and the first DB touch of the
    whole app (POST /api/auth/login) was what finally raised.

    Only the exception CLASS is reported, never its message: SQLAlchemy
    connection errors routinely embed the DSN, which contains the password.
    """
    session_factory = getattr(app.state, "db_sessionmaker", None)
    if session_factory is None:
        return False, "NotConfigured"
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001 — any driver/connection failure
        return False, type(exc).__name__


@app.get("/healthz")
def healthz() -> dict:
    store: TelemetryStore = app.state.telemetry_store
    consumer: TelemetryConsumer = app.state.telemetry_consumer
    broadcaster: TelemetryBroadcaster = app.state.telemetry_broadcaster
    db_connected, db_error = _db_status()
    return {
        "status": "ok",
        "mqtt_connected": consumer.is_connected(),
        "db_connected": db_connected,
        "db_error": db_error,
        "telemetry_count": store.count,
        "devices": store.devices(),
        "ws_clients": broadcaster.client_count,
    }
