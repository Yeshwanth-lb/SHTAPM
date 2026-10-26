"""Scenario-injection REST endpoints (FR-A4, FR-D7, Doc05 §05.7, D032).

    POST /api/devices/{device_id}/inject          analyst, admin -> 202
    POST /api/devices/{device_id}/inject/cancel   analyst, admin -> 200
    GET  /api/devices/{device_id}/inject          any scoped user -> active or null

Every inject/cancel attempt is written to ``audit_log`` (sent or not), and every
command actually handed to the broker is chained into the tamper-evident ledger
(Doc05 §05.6: "scenario inject -> analyst/admin; both write audit_log +
ledger_blocks"). Role denials are audited by ``require_role`` itself.

The backend remembers the last command it sent per device so the dashboard can
show what is running and for how long. That record is the backend's own view
-- "sent, expected to end at" -- not a confirmation from the edge; the observed
effect is the telemetry itself.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_device_access, require_role
from app.core.db import get_db
from app.models import User
from app.models.enums import UserRole
from app.mqtt.command_publisher import CommandPublisher
from app.schemas.command import (
    MAX_DURATION_S,
    CancelCommand,
    InjectCommand,
    InjectionScenario,
)
from app.schemas.contracts import Channel
from app.services import ledger as ledger_service
from app.services.audit import record as record_audit

router = APIRouter(prefix="/api/devices", tags=["inject"])

EVENT_SCENARIO_INJECT = "scenario_inject"
EVENT_SCENARIO_CANCEL = "scenario_cancel"


class InjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: InjectionScenario
    channel: Channel
    duration_s: int = Field(ge=1, le=MAX_DURATION_S)
    params: dict[str, float] = Field(default_factory=dict)


class InjectionOut(BaseModel):
    command_id: str
    device_id: str
    scenario: str
    kind: str
    channel: str
    duration_s: int
    params: dict[str, float]
    issued_by: str
    issued_at: datetime
    expires_at: datetime
    active: bool


class CancelOut(BaseModel):
    command_id: str
    cancelled: bool


class InjectionRegistry:
    """Last command sent per device (backend view, in memory)."""

    def __init__(self) -> None:
        self._by_device: dict[str, InjectionOut] = {}
        self._lock = threading.Lock()

    def set(self, injection: InjectionOut) -> None:
        with self._lock:
            self._by_device[injection.device_id] = injection

    def clear(self, device_id: str) -> InjectionOut | None:
        with self._lock:
            return self._by_device.pop(device_id, None)

    def get(self, device_id: str, now: datetime | None = None) -> InjectionOut | None:
        now = now or datetime.now(UTC)
        with self._lock:
            current = self._by_device.get(device_id)
        if current is None:
            return None
        return current.model_copy(update={"active": current.expires_at > now})


def get_command_publisher(request: Request) -> CommandPublisher:
    publisher = getattr(request.app.state, "command_publisher", None)
    if publisher is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "command channel not configured")
    return publisher


def get_injection_registry(request: Request) -> InjectionRegistry:
    registry = getattr(request.app.state, "injection_registry", None)
    if registry is None:
        registry = InjectionRegistry()
        request.app.state.injection_registry = registry
    return registry


def _validation_detail(error: ValidationError) -> list[dict]:
    return [{"loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]


@router.post(
    "/{device_id}/inject", response_model=InjectionOut, status_code=status.HTTP_202_ACCEPTED
)
def inject_scenario(
    device_id: str,
    body: InjectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst, UserRole.admin)),
    publisher: CommandPublisher = Depends(get_command_publisher),
    registry: InjectionRegistry = Depends(get_injection_registry),
) -> InjectionOut:
    device = require_device_access(db, user, device_id)
    issued_at = datetime.now(UTC)
    try:
        command = InjectCommand(
            action="inject",
            command_id=uuid.uuid4().hex,
            device_id=device.device_id,
            scenario=body.scenario,
            channel=body.channel,
            duration_s=body.duration_s,
            params=body.params,
            issued_by=user.email,
            issued_at=issued_at.isoformat(timespec="milliseconds"),
        )
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _validation_detail(e)) from e

    sent = publisher.publish(command)
    detail = {**command.model_dump(mode="json"), "kind": command.kind, "sent": sent}
    record_audit(
        db, user_id=user.id, action="scenario_inject", target=device.device_id, detail=detail
    )
    if not sent:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "MQTT broker unavailable; command not sent"
        )
    ledger_service.append(
        db,
        device_id=device.id,
        event_type=EVENT_SCENARIO_INJECT,
        payload={
            "command_id": command.command_id,
            "scenario": command.scenario,
            "kind": command.kind,
            "channel": command.channel.value,
            "duration_s": command.duration_s,
            "params": command.params,
            "issued_by": command.issued_by,
            "issued_at": command.issued_at,
        },
    )
    injection = InjectionOut(
        command_id=command.command_id,
        device_id=device.device_id,
        scenario=command.scenario,
        kind=command.kind,
        channel=command.channel.value,
        duration_s=command.duration_s,
        params=command.params,
        issued_by=command.issued_by,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=command.duration_s),
        active=True,
    )
    registry.set(injection)
    return injection


@router.post("/{device_id}/inject/cancel", response_model=CancelOut)
def cancel_scenario(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst, UserRole.admin)),
    publisher: CommandPublisher = Depends(get_command_publisher),
    registry: InjectionRegistry = Depends(get_injection_registry),
) -> CancelOut:
    device = require_device_access(db, user, device_id)
    current = registry.get(device.device_id)
    # "*" cancels whatever the edge is running, even one this backend process
    # did not issue (e.g. after a backend restart).
    target_id = current.command_id if current is not None and current.active else "*"
    command = CancelCommand(
        action="cancel",
        command_id=target_id,
        device_id=device.device_id,
        issued_by=user.email,
        issued_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
    )
    sent = publisher.publish(command)
    record_audit(
        db,
        user_id=user.id,
        action="scenario_cancel",
        target=device.device_id,
        detail={**command.model_dump(mode="json"), "sent": sent},
    )
    if not sent:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "MQTT broker unavailable; cancel not sent"
        )
    ledger_service.append(
        db,
        device_id=device.id,
        event_type=EVENT_SCENARIO_CANCEL,
        payload={
            "command_id": target_id,
            "issued_by": command.issued_by,
            "issued_at": command.issued_at,
        },
    )
    registry.clear(device.device_id)
    return CancelOut(command_id=target_id, cancelled=True)


@router.get("/{device_id}/inject", response_model=InjectionOut | None)
def get_active_injection(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: InjectionRegistry = Depends(get_injection_registry),
) -> InjectionOut | None:
    device = require_device_access(db, user, device_id)
    return registry.get(device.device_id)
