"""``/api/system/health`` (P4-M4 · Doc05 §05.7, admin-only).

``e2e_latency_ms`` is reported as ``null`` here, not fabricated: the only
place this system has ever actually measured sensor→client latency is the
hardware-free WS probe (``frontend/scripts/latency_probe.mjs``, a one-off
script) — there is no continuous latency measurement wired into the
running backend to report a live number from.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.db import get_db
from app.models.enums import UserRole
from app.mqtt.consumer import TelemetryConsumer
from app.ws.broadcaster import TelemetryBroadcaster

router = APIRouter(prefix="/api/system", tags=["system"])


class SystemHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mqtt_connected: bool
    db_connected: bool
    ws_clients: int
    telemetry_count: int
    e2e_latency_ms: float | None = None


@router.get("/health", response_model=SystemHealthOut)
def system_health(
    request: Request,
    db: Session = Depends(get_db),
    _admin: object = Depends(require_role(UserRole.admin)),
) -> SystemHealthOut:
    consumer: TelemetryConsumer = request.app.state.telemetry_consumer
    broadcaster: TelemetryBroadcaster = request.app.state.telemetry_broadcaster
    try:
        db.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False
    return SystemHealthOut(
        mqtt_connected=consumer.is_connected(),
        db_connected=db_connected,
        ws_clients=broadcaster.client_count,
        telemetry_count=request.app.state.telemetry_store.count,
    )
