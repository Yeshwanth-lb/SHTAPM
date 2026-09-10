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

``channels`` (Doc05 §05.2 ``sensors`` registry) answers "what is behind
each of the six frozen channels, and is it real?" — the question the wire
frame itself cannot answer, since a placeholder constant and a measured
value are both just floats. See ``ChannelOut`` for exactly which parts of
that answer are stored, which are declared configuration, and which are
honestly reported as unknown.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_device_access, require_role, scope_devices_query
from app.core.config import ChannelSourceSettings
from app.core.db import get_db
from app.models import Decision, Device, Sensor, SensorReading, Threshold, User
from app.models.enums import DeviceStatus, UserRole
from app.schemas.contracts import CHANNELS, Attribution, HealthState, RLAction
from app.schemas.decision_diagnostic import DIAGNOSTIC_PROVENANCE
from app.services import ledger as ledger_service

router = APIRouter(prefix="/api/devices", tags=["devices"])

# Engineering unit of each frozen channel, per PRD §12.1's sensor table. This
# is a property of the CHANNEL definition, not a claim about which part is
# wired: `pressure` is hPa whether a BMP280 is connected or the channel is a
# placeholder constant. Provenance stays in `part`/`source`, which remain null/
# "unknown" until the backend is actually told (see ChannelOut).
#
# Mirrors edge/drivers/registry.py's own `_UNITS` — same six values, and the
# real drivers emit exactly these (e.g. DS18B20Driver/DHT22AdafruitTemperature
# both use "°C"). A `sensors` registry row, when one exists, overrides this.
_CANONICAL_CHANNEL_UNITS: dict[str, str] = {
    "temperature": "°C",
    "vibration": "g",
    "pressure": "hPa",
    "humidity": "%",
    "gas": "ppm",
    "current": "A",
}

# Cap on a single readings page. At 1 Hz an uncapped query grows without bound
# (~86k rows/device/day), which a browser chart must never pull.
_MAX_READINGS_LIMIT = 5000

# Interface wiring, keyed by (channel, registered part) so it can only ever
# describe a part the registry actually names. Every string is transcribed from
# this repository; a pairing that is not documented is simply absent, and the
# API then reports `interface: null` rather than a plausible guess.
#
#   DHT22    edge/drivers/dht22_adafruit.py + DECISIONS.md D028 (one part,
#            GPIO17, serving BOTH temperature and humidity)
#   ADXL335  edge/drivers/adxl335.py (X/Y/Z on MCP3008 CH0-2 over SPI0 CE0 —
#            three ADC channels, so it is never described as a single one)
#   BMP280   edge/drivers/bmp280.py (I2C bus 1, address 0x76)
#   INA219   edge/drivers/ina219.py (I2C bus 1, address 0x40)
#
# MQ-135 is absent on purpose: no driver exists and no wiring is documented, so
# no ADC channel may be shown for `gas`.
_DOCUMENTED_INTERFACES: dict[tuple[str, str], str] = {
    ("temperature", "DHT22"): "GPIO17",
    ("humidity", "DHT22"): "GPIO17",
    ("vibration", "ADXL335"): "MCP3008 CH0-2 / SPI0 CE0",
    ("pressure", "BMP280"): "I2C bus 1 @ 0x76",
    ("current", "INA219"): "I2C bus 1 @ 0x40",
}

# Measurement caveats a dashboard must carry with the value. These are
# documented properties, not warnings invented here.
_CHANNEL_NOTES: dict[str, str] = {
    "temperature": (
        "Ambient air temperature, from the same physical DHT22 as humidity "
        "(PRD 12.1, D028). Not a contact motor/bearing reading, and not an "
        "independent corroboration of humidity."
    ),
    "humidity": (
        "From the same physical DHT22 as temperature (PRD 12.1, D028). The two "
        "channels share one part and one air mass, so their agreement is not "
        "independent corroboration."
    ),
    "pressure": "Barometric/atmospheric pressure — a proxy, not water-line pressure (PRD 12.1).",
    "gas": "VOC/CO2 proxy, not H2S (PRD 12.1).",
}


class ChannelSource(str, Enum):
    """What the API is willing to say about a channel's physical backing."""

    live = "live"
    placeholder = "placeholder"
    unknown = "unknown"


def resolve_channel_source(declared: str, registered_part: str | None) -> tuple[str, str | None]:
    """Reconcile the declaration with the registry. Returns (source, conflict).

    THE INVARIANT: a channel is reported ``live`` only when BOTH
      (a) ``SHTAPM_CHANNEL_SOURCES`` declares it live — an explicit, trusted
          statement that something is physically attached, and
      (b) the ``sensors`` registry names the part that is attached.

    A telemetry value NEVER contributes. Placeholder constants are
    byte-identical to measurements on the wire, so no amount of arriving data
    can promote a channel.

    The failure this guards is a confident lie: declaring ``pressure=live``
    while nothing is registered would otherwise render a green LIVE badge over
    a constant. Rather than trust the declaration, the channel degrades to
    ``unknown`` and the reason is returned so the UI can show it.

    Note what is deliberately NOT a conflict: ``is_proxy`` is orthogonal to
    connectedness. A wired BMP280 is a live proxy — it genuinely measures, just
    not the quantity the channel name suggests. Conflating the two would make
    it impossible to ever report a connected proxy honestly.

    Downgrades only. A declaration is never upgraded by registry contents:
    an undeclared channel with a fully populated registry row stays ``unknown``,
    because nobody has said anything is plugged in.
    """
    if declared == ChannelSource.live.value:
        if registered_part is None:
            return ChannelSource.unknown.value, (
                "declared live but no part is registered for this channel, so there is "
                "nothing to be live; reporting unverified instead"
            )
        return ChannelSource.live.value, None
    # placeholder and unknown pass through untouched — neither can become live.
    return declared, None


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
    # Per-channel trust (Doc05 §05.2 decisions.trust_*). These columns have
    # always been written by the decision_diagnostic ingestion path; they were
    # simply absent from this response schema, so the six scores the trust
    # panel needs were unreachable over REST.
    trust_temperature: float | None
    trust_vibration: float | None
    trust_pressure: float | None
    trust_humidity: float | None
    trust_gas: float | None
    trust_current: float | None
    health_state: HealthState | None
    failure_eta: float | None
    rl_action: RLAction | None
    isolated_channels: list[str] | None
    substituted_channels: list[str] | None


class DecisionProvenanceOut(_Body):
    """The decision producer's own self-labelling.

    Sourced from ``DecisionDiagnosticMessage``'s ``Literal`` fields, which are
    invariant by construction — the only producer that writes to ``decisions``
    is the diagnostic path, and it can emit exactly one value for each. They
    are therefore reported here as the constants they are, NOT stored per row:
    Doc05 §05.2's ``decisions`` table defines no such columns, and persisting
    an invariant on every 1 Hz row would add a schema deviation and ~86k
    identical strings a day for no recoverable information.

    If a second producer with a different provenance is ever added, this stops
    being invariant and must become real per-row columns (schema change,
    migration, and a Doc05 amendment). Until then this is the honest shape.
    """

    execution_mode: str
    data_source: str
    model_status: str
    note: str


class ChannelOut(_Body):
    """One frozen channel's provenance.

    Three different kinds of fact, deliberately not blended:
      * ``part``/``is_proxy``/``display_hue`` — STORED, from the Doc05 §05.2
        ``sensors`` registry. ``null`` when no row exists yet (nothing seeds
        that table today), never invented.
      * ``unit`` — the CHANNEL's engineering unit (PRD §12.1), used when the
        registry has no row. A unit is a property of the channel, not of the
        part behind it, so supplying it asserts nothing about provenance: a
        placeholder `pressure` is still hPa. A registry row overrides it.
      * ``source`` — the RECONCILIATION of the declared configuration
        (``SHTAPM_CHANNEL_SOURCES``) with the registry, via
        ``resolve_channel_source``. ``"live"`` requires both a declaration AND
        a registered part; ``"unknown"`` means this backend was not told, and a
        UI must render that differently from ``"placeholder"``, which is a
        positive claim that nothing is connected. Never derived from values.
      * ``conflict`` — why a declaration was not honoured, when it was not.
      * ``interface``/``note`` — documented wiring and measurement caveats,
        looked up by (channel, part) so they can never describe a part the
        registry does not name.
      * ``channel`` — the frozen contract's own channel name.
    """

    channel: str
    part: str | None
    unit: str | None
    is_proxy: bool | None
    display_hue: str | None
    source: str
    #: Documented wiring for (channel, part). ``null`` when the pairing is not
    #: documented — notably ``gas``, which has no driver and no known wiring.
    interface: str | None
    #: Documented measurement caveat (proxy nature, shared part). ``null`` when
    #: the channel carries none.
    note: str | None
    #: Set when the declaration and the registry disagree and the channel was
    #: therefore NOT reported as live. ``null`` when they agree.
    conflict: str | None


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
    limit: int | None = Query(default=None, ge=1, le=_MAX_READINGS_LIMIT),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SensorReadingOut]:
    """Raw readings, oldest-first.

    ``limit`` (optional, added for the device history chart) returns the MOST
    RECENT ``limit`` rows, still oldest-first so a chart can plot them without
    reversing. Omitting it preserves the previous unbounded behaviour exactly,
    so existing callers are unaffected.
    """
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
    if limit is None:
        rows = query.order_by(SensorReading.ts).all()
    else:
        # Newest-first + limit, then flip: taking the FIRST n ascending would
        # return the oldest rows, which is the opposite of what a live chart wants.
        rows = list(reversed(query.order_by(SensorReading.ts.desc()).limit(limit).all()))
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


@router.get("/{device_id}/decisions/provenance", response_model=DecisionProvenanceOut)
def get_decisions_provenance(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionProvenanceOut:
    """How decision rows for this device were produced. See
    ``DecisionProvenanceOut`` for why these are constants, not stored values."""
    require_device_access(db, current_user, device_id)
    return DecisionProvenanceOut(**DIAGNOSTIC_PROVENANCE)


@router.get("/{device_id}/channels", response_model=list[ChannelOut])
def get_channels(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChannelOut]:
    """Per-channel provenance for the six frozen channels, in contract order.

    Always returns all six — a channel with no ``sensors`` row is reported
    with null registry fields rather than omitted, so a client can never
    silently miss one.
    """
    device = require_device_access(db, current_user, device_id)
    rows = {
        row.channel.value if hasattr(row.channel, "value") else str(row.channel): row
        for row in db.query(Sensor).filter(Sensor.device_id == device.id).all()
    }
    settings = ChannelSourceSettings.from_env()

    out: list[ChannelOut] = []
    for channel in CHANNELS:
        row = rows.get(channel)
        part = getattr(row, "part", None)
        source, conflict = resolve_channel_source(settings.source_for(channel), part)
        out.append(
            ChannelOut(
                channel=channel,
                part=part,
                unit=getattr(row, "unit", None) or _CANONICAL_CHANNEL_UNITS.get(channel),
                is_proxy=getattr(row, "is_proxy", None),
                display_hue=getattr(row, "display_hue", None),
                source=source,
                interface=_DOCUMENTED_INTERFACES.get((channel, part)) if part else None,
                note=_CHANNEL_NOTES.get(channel),
                conflict=conflict,
            )
        )
    return out


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
