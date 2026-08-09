"""SHTAPM FastAPI backend (P0 M3.3) — MQTT telemetry ingestion only.

Lifespan starts the MQTT telemetry consumer as a background task (paho's own
thread) and exposes the validated in-memory ``TelemetryStore`` on
``app.state`` so M3.4 (WebSocket fan-out) can consume it without changing this
ingestion layer. Broker downtime is tolerated: the consumer connects async and
retries, so the app still starts and stays up (TRD principle: degrade
gracefully).

Scope: NO persistence, auth, REST history, WebSocket, decisions, or ledger.
``/healthz`` is a minimal liveness/observability endpoint (no auth, no data
history), useful for demos and for M3.4 wiring.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import MqttSettings
from app.mqtt.consumer import TelemetryConsumer
from app.services.telemetry_store import TelemetryStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = TelemetryStore()
    consumer = TelemetryConsumer(store)
    settings = MqttSettings.from_env()
    consumer.start(settings.host, settings.port)  # non-blocking; tolerates broker down
    app.state.telemetry_store = store
    app.state.telemetry_consumer = consumer
    try:
        yield
    finally:
        consumer.stop()


app = FastAPI(title="SHTAPM backend (P0 M3.3)", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    store: TelemetryStore = app.state.telemetry_store
    consumer: TelemetryConsumer = app.state.telemetry_consumer
    return {
        "status": "ok",
        "mqtt_connected": consumer.is_connected(),
        "telemetry_count": store.count,
        "devices": store.devices(),
    }
