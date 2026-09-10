"""``/api/alerts`` (P4-M4 · Doc05 §05.7).

Doc05's ``alerts`` table has no literal ``status`` column (only
``acknowledged_by``/``acknowledged_at``) — the REST spec's ``status`` filter
is interpreted here as the only two states that pair of columns can
represent: ``"open"`` (``acknowledged_at IS NULL``) and ``"acknowledged"``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, scope_devices_query
from app.core.db import get_db
from app.models import Alert, Device, User
from app.models.enums import AlertSeverity, AlertType, UserRole

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Bounded like the telemetry/decision endpoints: an alert table with a real
# producer grows without limit, and a browser must never pull all of it.
_MAX_ALERTS_LIMIT = 1000
_DEFAULT_ALERTS_LIMIT = 200


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AlertOut(_Body):
    id: str
    device_id: str
    ts: datetime
    severity: AlertSeverity
    type: AlertType
    channel: str | None
    message: str
    reason: str | None
    acknowledged_by: str | None
    acknowledged_at: datetime | None


def _to_alert_out(alert: Alert, device_wire_id: str) -> AlertOut:
    return AlertOut(
        id=str(alert.id),
        device_id=device_wire_id,
        ts=alert.ts,
        severity=alert.severity,
        type=alert.type,
        channel=alert.channel,
        message=alert.message,
        reason=alert.reason,
        acknowledged_by=str(alert.acknowledged_by) if alert.acknowledged_by else None,
        acknowledged_at=alert.acknowledged_at,
    )


@router.get("", response_model=list[AlertOut])
def list_alerts(
    device: str | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_ALERTS_LIMIT, ge=1, le=_MAX_ALERTS_LIMIT),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AlertOut]:
    if status_filter is not None and status_filter not in ("open", "acknowledged"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "status must be 'open' or 'acknowledged'"
        )

    owned_devices = scope_devices_query(db.query(Device), current_user)
    query = db.query(Alert, Device).join(Device, Alert.device_id == Device.id).filter(
        Device.id.in_(owned_devices.with_entities(Device.id))
    )

    if device is not None:
        target = db.query(Device).filter(Device.device_id == device).one_or_none()
        if target is None or (
            current_user.role != UserRole.admin and target.owner_user_id != current_user.id
        ):
            return []  # unknown/not-owned device — empty, not an error (RLS-style)
        query = query.filter(Alert.device_id == target.id)

    if status_filter == "open":
        query = query.filter(Alert.acknowledged_at.is_(None))
    elif status_filter == "acknowledged":
        query = query.filter(Alert.acknowledged_at.isnot(None))

    # Newest-first + limit: the most recent alerts are the operationally
    # relevant ones, so truncation drops the oldest rather than the newest.
    rows = query.order_by(Alert.ts.desc()).limit(limit).all()
    return [_to_alert_out(alert, device.device_id) for alert, device in rows]


@router.post("/{alert_id}/ack", response_model=AlertOut)
def acknowledge_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertOut:
    try:
        alert_uuid = uuid.UUID(alert_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found") from exc
    alert = db.query(Alert).filter(Alert.id == alert_uuid).one_or_none()
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    device = db.get(Device, alert.device_id)
    if device is None or (
        current_user.role != UserRole.admin and device.owner_user_id != current_user.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")

    alert.acknowledged_by = current_user.id
    alert.acknowledged_at = datetime.now(UTC)
    db.commit()
    db.refresh(alert)
    return _to_alert_out(alert, device.device_id)
