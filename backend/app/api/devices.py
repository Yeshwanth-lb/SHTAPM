"""``/api/devices`` (P4-M4 · Doc05 §05.7).

Path devices are addressed by the wire ``device_id`` string (e.g.
``"pump-01"``), not the internal UUID PK — consistent with MQTT topics and
the existing ``/ws?device_id=`` filter; nothing else in this system
addresses a device by its UUID.

``readings``/``decisions`` return raw rows only — the continuous
aggregates Doc05 §05.3 describes in prose (``readings_1min``,
``decisions_5min``) were deliberately deferred at P4-M1 (no consumer
exists yet, exact column shape unspecified); ``agg`` therefore only
accepts ``"raw"`` (the default) here, and any other value is a clear 400
rather than a silently-wrong aggregation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_device_access, require_role, scope_devices_query
from app.core.db import get_db
from app.models import Decision, Device, SensorReading, Threshold, User
from app.models.enums import DeviceStatus, UserRole
from app.schemas.contracts import Attribution, HealthState, RLAction
from app.services import ledger as ledger_service

router = APIRouter(prefix="/api/devices", tags=["devices"])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceOut(_Body):
    id: str
    device_id: str
    name: str
    location: str | None
    owner_user_id: str | None
    status: DeviceStatus
    health_state: HealthState
    last_seen_at: datetime | None
    sample_rate_hz: int
    created_at: datetime


class DeviceCreate(_Body):
    device_id: str
    name: str
    location: str | None = None
    owner_user_id: uuid.UUID | None = None
    sample_rate_hz: int = 1


class DeviceUpdate(_Body):
    name: str | None = None
    location: str | None = None
    owner_user_id: uuid.UUID | None = None
    sample_rate_hz: int | None = None


class SensorReadingOut(_Body):
    ts: datetime
    sample_seq: int
    temperature: float
    vibration: float
    pressure: float
    humidity: float
    gas: float
    current: float
    healthy_mask: int


class DecisionOut(_Body):
    ts: datetime
    anomaly_flag: bool | None
    anomaly_severity: float | None
    attribution: Attribution | None
    reason: str | None
    health_state: HealthState | None
    failure_eta: float | None
    rl_action: RLAction | None
    isolated_channels: list[str] | None
    substituted_channels: list[str] | None


class ThresholdOut(_Body):
    trust_trusted_min: float
    trust_malicious_max: float
    trust_w_consistency: float
    trust_w_correlation: float
    trust_w_reliability: float
    window_size: int
    substitution_max_seconds: int
    divergence_threshold: float | None
    updated_by: str | None
    updated_at: datetime | None


class ThresholdUpdate(_Body):
    trust_trusted_min: float | None = None
    trust_malicious_max: float | None = None
    trust_w_consistency: float | None = None
    trust_w_correlation: float | None = None
    trust_w_reliability: float | None = None
    window_size: int | None = None
    substitution_max_seconds: int | None = None
    divergence_threshold: float | None = None


def _to_threshold_out(threshold: Threshold) -> ThresholdOut:
    return ThresholdOut(
        trust_trusted_min=threshold.trust_trusted_min,
        trust_malicious_max=threshold.trust_malicious_max,
        trust_w_consistency=threshold.trust_w_consistency,
        trust_w_correlation=threshold.trust_w_correlation,
        trust_w_reliability=threshold.trust_w_reliability,
        window_size=threshold.window_size,
        substitution_max_seconds=threshold.substitution_max_seconds,
        divergence_threshold=threshold.divergence_threshold,
        updated_by=str(threshold.updated_by) if threshold.updated_by else None,
        updated_at=threshold.updated_at,
    )


def _to_device_out(device: Device) -> DeviceOut:
    return DeviceOut(
        id=str(device.id),
        device_id=device.device_id,
        name=device.name,
        location=device.location,
        owner_user_id=str(device.owner_user_id) if device.owner_user_id else None,
        status=device.status,
        health_state=device.health_state,
        last_seen_at=device.last_seen_at,
        sample_rate_hz=device.sample_rate_hz,
        created_at=device.created_at,
    )


@router.get("", response_model=list[DeviceOut])
def list_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DeviceOut]:
    query = scope_devices_query(db.query(Device), current_user)
    return [_to_device_out(d) for d in query.all()]


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
def create_device(
    body: DeviceCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> DeviceOut:
    device = Device(
        device_id=body.device_id,
        name=body.name,
        location=body.location,
        owner_user_id=body.owner_user_id,
        sample_rate_hz=body.sample_rate_hz,
    )
    db.add(device)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "device_id already registered") from exc
    db.refresh(device)
    return _to_device_out(device)


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeviceOut:
    device = require_device_access(db, current_user, device_id)
    return _to_device_out(device)


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: str,
    body: DeviceUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
) -> DeviceOut:
    device = require_device_access(db, admin, device_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    db.commit()
    db.refresh(device)
    return _to_device_out(device)


@router.get("/{device_id}/readings", response_model=list[SensorReadingOut])
def get_readings(
    device_id: str,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    agg: str = Query(default="raw"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SensorReadingOut]:
    if agg != "raw":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "aggregation is not implemented yet (Doc05 continuous aggregates deferred); "
            "only agg=raw (the default) is supported",
        )
    device = require_device_access(db, current_user, device_id)
    query = db.query(SensorReading).filter(SensorReading.device_id == device.id)
    if from_ is not None:
        query = query.filter(SensorReading.ts >= from_)
    if to is not None:
        query = query.filter(SensorReading.ts <= to)
    rows = query.order_by(SensorReading.ts).all()
    return [SensorReadingOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{device_id}/decisions", response_model=list[DecisionOut])
def get_decisions(
    device_id: str,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DecisionOut]:
    device = require_device_access(db, current_user, device_id)
    query = db.query(Decision).filter(Decision.device_id == device.id)
    if from_ is not None:
        query = query.filter(Decision.ts >= from_)
    if to is not None:
        query = query.filter(Decision.ts <= to)
    rows = query.order_by(Decision.ts).all()
    return [DecisionOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{device_id}/thresholds", response_model=ThresholdOut)
def get_thresholds(
    device_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
) -> ThresholdOut:
    device = require_device_access(db, admin, device_id)
    threshold = db.get(Threshold, device.id)
    if threshold is None:
        # Doc05 §05.4: devices 1───1 thresholds. Lazily create the row with
        # its documented column defaults (divergence_threshold stays NULL —
        # U05, never silently defaulted) rather than 404ing a relationship
        # Doc05 describes as always-present.
        threshold = Threshold(device_id=device.id)
        db.add(threshold)
        db.commit()
        db.refresh(threshold)
    return _to_threshold_out(threshold)


@router.patch("/{device_id}/thresholds", response_model=ThresholdOut)
def update_thresholds(
    device_id: str,
    body: ThresholdUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
) -> ThresholdOut:
    device = require_device_access(db, admin, device_id)
    threshold = db.get(Threshold, device.id)
    if threshold is None:
        threshold = Threshold(device_id=device.id)
        db.add(threshold)
    changed = body.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(threshold, field, value)
    threshold.updated_by = admin.id
    threshold.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(threshold)

    if changed:
        # Safety-relevant config change → tamper-evident ledger (D004), not
        # just the audit_log RBAC trail — see app.services.ledger docstring.
        ledger_service.append(
            db,
            device_id=device.id,
            event_type="config_update",
            payload={"target": "thresholds", "changed": changed, "updated_by": str(admin.id)},
        )
    return _to_threshold_out(threshold)
