"""Dead-sensor status for the dashboard (D045).

    GET /api/devices/{device_id}/sensor-health   any scoped user

Returns the sensors the edge currently reports as stale (stopped responding,
publishing their last good reading) and since when. Empty means every sensor
answered on the latest decision -- not a claim about calibration or accuracy.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_device_access
from app.core.db import get_db
from app.models import User
from app.services.sensor_health import SensorHealthRegistry

router = APIRouter(prefix="/api/devices", tags=["sensor-health"])


class SensorHealthOut(BaseModel):
    device_id: str
    stale: dict[str, str]  # channel -> first reported stale (ISO ts)


def get_sensor_health_registry(request: Request) -> SensorHealthRegistry:
    registry = getattr(request.app.state, "sensor_health_registry", None)
    if registry is None:
        registry = SensorHealthRegistry()
        request.app.state.sensor_health_registry = registry
    return registry


@router.get("/{device_id}/sensor-health", response_model=SensorHealthOut)
def get_sensor_health(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: SensorHealthRegistry = Depends(get_sensor_health_registry),
) -> SensorHealthOut:
    device = require_device_access(db, user, device_id)
    return SensorHealthOut(device_id=device.device_id, stale=registry.get(device.device_id))
