"""Pump relay REST endpoints (FR-R1, PRD §18.3 item 3, D041).

    GET  /api/devices/{device_id}/relay   any scoped user -> latest relay status
    POST /api/devices/{device_id}/relay   admin only      -> start / stop

Starting or stopping a pump is a physical action, so it is admin-only (role
denials are audited by ``require_role``). Every attempt is written to
``audit_log`` (sent or not); a command actually handed to the broker is chained
into the ledger as ``relay_command``. The edge's own report of what happened
arrives separately on ``shtapm/{id}/actuation`` and is chained as
``relay_on`` / ``relay_off`` / ``safe_stop`` -- so the ledger holds both the
request and the outcome.

The GET returns the edge's REPORTED state, never the backend's guess: until the
edge reports, it says so (``known: false``). ``hardware: false`` means the edge
runs the safety logic against an in-memory relay -- nothing is switched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_device_access, require_role
from app.api.inject import get_command_publisher
from app.core.db import get_db
from app.models import User
from app.models.enums import UserRole
from app.mqtt.command_publisher import CommandPublisher
from app.schemas.actuation import ActuationStatus, RelayCommand, RelayState
from app.services import ledger as ledger_service
from app.services.actuation import EVENT_RELAY_COMMAND, ActuationRegistry
from app.services.audit import record as record_audit

router = APIRouter(prefix="/api/devices", tags=["relay"])


class RelayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: RelayState


class RelayOut(BaseModel):
    device_id: str
    known: bool
    status: ActuationStatus | None = None


class RelayCommandOut(BaseModel):
    command_id: str
    device_id: str
    state: RelayState
    issued_by: str
    issued_at: datetime


def get_actuation_registry(request: Request) -> ActuationRegistry:
    registry = getattr(request.app.state, "actuation_registry", None)
    if registry is None:
        registry = ActuationRegistry()
        request.app.state.actuation_registry = registry
    return registry


@router.get("/{device_id}/relay", response_model=RelayOut)
def get_relay(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: ActuationRegistry = Depends(get_actuation_registry),
) -> RelayOut:
    device = require_device_access(db, user, device_id)
    latest = registry.get(device.device_id)
    return RelayOut(device_id=device.device_id, known=latest is not None, status=latest)


@router.post(
    "/{device_id}/relay", response_model=RelayCommandOut, status_code=status.HTTP_202_ACCEPTED
)
def command_relay(
    device_id: str,
    body: RelayRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
    publisher: CommandPublisher = Depends(get_command_publisher),
) -> RelayCommandOut:
    device = require_device_access(db, user, device_id)
    issued_at = datetime.now(UTC)
    command = RelayCommand(
        action="relay",
        command_id=uuid.uuid4().hex,
        device_id=device.device_id,
        state=body.state,
        issued_by=user.email,
        issued_at=issued_at.isoformat(timespec="milliseconds"),
    )
    sent = publisher.publish(command)
    record_audit(
        db,
        user_id=user.id,
        action="relay_command",
        target=device.device_id,
        detail={**command.model_dump(mode="json"), "sent": sent},
    )
    if not sent:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "MQTT broker unavailable; command not sent"
        )
    ledger_service.append(
        db,
        device_id=device.id,
        event_type=EVENT_RELAY_COMMAND,
        payload=command.model_dump(mode="json"),
    )
    return RelayCommandOut(
        command_id=command.command_id,
        device_id=device.device_id,
        state=command.state,
        issued_by=command.issued_by,
        issued_at=issued_at,
    )
