"""``/api/system/health`` (P4-M4 · Doc05 §05.7, admin-only).

``e2e_latency_ms`` is now a real measurement taken from the live stream
(``app.services.latency_tracker``): the interval between the timestamp the edge
stamped on a frame and the moment this backend received it.

Two honesty constraints travel with that number:

  * It is **edge→backend**, not sensor→UI. The browser rendering leg is not
    included, so it is a LOWER BOUND on the figure PRD NFR-P1/AC6 asks about.
    The field keeps its Doc05 name; ``e2e_latency_note`` states what it covers.
  * It is ``null`` when unmeasurable — no frames yet, or the edge and backend
    clocks disagree (see the tracker's own docstring). A null meaning "cannot
    measure" is more useful than a fabricated zero.
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
from app.services.latency_tracker import LatencySnapshot
from app.ws.broadcaster import TelemetryBroadcaster

router = APIRouter(prefix="/api/system", tags=["system"])


class SystemHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mqtt_connected: bool
    db_connected: bool
    ws_clients: int
    telemetry_count: int
    # Doc05 §05.7's field name, kept. p50 of the rolling window; null when not
    # measurable. See module docstring for what this leg does and does not cover.
    e2e_latency_ms: float | None = None
    e2e_latency_p95_ms: float | None = None
    e2e_latency_samples: int = 0
    e2e_latency_note: str = ""
    clock_skew_suspected: bool = False


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
    latency = request.app.state.latency_tracker.snapshot()
    return SystemHealthOut(
        mqtt_connected=consumer.is_connected(),
        db_connected=db_connected,
        ws_clients=broadcaster.client_count,
        telemetry_count=request.app.state.telemetry_store.count,
        e2e_latency_ms=latency.p50_ms,
        e2e_latency_p95_ms=latency.p95_ms,
        e2e_latency_samples=latency.samples,
        e2e_latency_note=_latency_note(latency),
        clock_skew_suspected=latency.clock_skew_suspected,
    )


def _latency_note(latency: LatencySnapshot) -> str:
    """Say what the number means, or why there isn't one.

    A consumer should never have to guess whether a null means "fast" or
    "unknown"."""
    if latency.clock_skew_suspected:
        return (
            f"unmeasurable: {latency.negative_samples} frame(s) appeared to arrive "
            "before they were sent, so the edge and backend clocks disagree"
        )
    if latency.samples == 0:
        return "unmeasurable: no telemetry received yet"
    return "edge publish to backend receipt; excludes browser rendering"
