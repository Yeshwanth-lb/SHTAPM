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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
configure_cors(app)
app.include_router(ws_router)
app.include_router(auth_router)
app.include_router(devices_router)
app.include_router(alerts_router)
app.include_router(users_router)
app.include_router(system_router)
app.include_router(ledger_router)


@app.get("/healthz")
def healthz() -> dict:
    store: TelemetryStore = app.state.telemetry_store
    consumer: TelemetryConsumer = app.state.telemetry_consumer
    broadcaster: TelemetryBroadcaster = app.state.telemetry_broadcaster
    return {
        "status": "ok",
        "mqtt_connected": consumer.is_connected(),
        "telemetry_count": store.count,
        "devices": store.devices(),
        "ws_clients": broadcaster.client_count,
    }
