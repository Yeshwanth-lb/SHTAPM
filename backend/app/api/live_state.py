"""Live physics view for the dashboard (D054).

    GET /api/devices/{device_id}/live-state   any scoped user

``motor_state``: what current and vibration each say about the motor in the
newest window (idle / running / unclear, the window median, the bands that
judged it). ``twin_values``: the digital twin's reconstructed value for each
channel it is substituting, in engineering units. Both null/empty until the
edge reports them (an older edge never does).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_device_access
from app.core.db import get_db
from app.models import User
from app.schemas.decision_diagnostic import ChannelMotorState
from app.services.live_state import LiveStateRegistry

router = APIRouter(prefix="/api/devices", tags=["live-state"])


class LiveStateOut(BaseModel):
    device_id: str
    ts: str | None
    motor_state: dict[str, ChannelMotorState] | None
    twin_values: dict[str, float]


def get_live_state_registry(request: Request) -> LiveStateRegistry:
    registry = getattr(request.app.state, "live_state_registry", None)
    if registry is None:
        registry = LiveStateRegistry()
        request.app.state.live_state_registry = registry
    return registry


@router.get("/{device_id}/live-state", response_model=LiveStateOut)
def get_live_state(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: LiveStateRegistry = Depends(get_live_state_registry),
) -> LiveStateOut:
    device = require_device_access(db, user, device_id)
    latest = registry.get(device.device_id)
    if latest is None:
        return LiveStateOut(device_id=device.device_id, ts=None, motor_state=None, twin_values={})
    return LiveStateOut(
        device_id=device.device_id,
        ts=latest.ts,
        motor_state=dict(latest.motor_state) if latest.motor_state else None,
        twin_values=dict(latest.twin_values),
    )
