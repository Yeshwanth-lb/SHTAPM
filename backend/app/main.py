"""SHTAPM FastAPI backend (P0 M3.4) — MQTT telemetry ingestion + WebSocket fan-out.

Lifespan starts the MQTT telemetry consumer (paho's own thread) and a
``TelemetryBroadcaster`` (the seam to WebSocket clients), wiring the consumer's
sink to the broadcaster so each validated telemetry message is pushed live to
connected ``/ws`` clients. The in-memory ``TelemetryStore`` remains the latest
state. Broker downtime is tolerated: the consumer connects async and retries, so
the app still starts and stays up (TRD principle: degrade gracefully).

Scope: NO persistence, auth, REST history, decisions, or ledger. ``/healthz`` is
a minimal liveness/observability endpoint (no auth, no data history). ``/ws``
serves live telemetry frames only.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import MqttSettings
from app.mqtt.consumer import TelemetryConsumer
from app.services.telemetry_store import TelemetryStore
from app.ws.broadcaster import TelemetryBroadcaster
from app.ws.routes import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = TelemetryStore()
    broadcaster = TelemetryBroadcaster(asyncio.get_running_loop())
    consumer = TelemetryConsumer(store)
    consumer.add_sink(broadcaster.publish_from_thread)  # MQTT → WS seam
    settings = MqttSettings.from_env()
    consumer.start(settings.host, settings.port)  # non-blocking; tolerates broker down
    app.state.telemetry_store = store
    app.state.telemetry_broadcaster = broadcaster
    app.state.telemetry_consumer = consumer
    try:
        yield
    finally:
        consumer.stop()


app = FastAPI(title="SHTAPM backend (P0 M3.4)", lifespan=lifespan)
app.include_router(ws_router)


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
