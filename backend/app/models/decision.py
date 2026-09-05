"""``decisions`` table (Doc05 §05.2) — TimescaleDB hypertable in prod.

Composite PK ``(device_id, ts)``, no surrogate ``id`` (Doc05 §05.1 exception,
same as ``sensor_readings``). No P2/P3 component publishes ``DecisionMessage``
over MQTT yet (see project-state/CURRENT_STATE.md), so this table has no
ingestion path in this P4 slice — it exists so the schema matches Doc05 and
the read-side REST endpoint (``GET /api/devices/:id/decisions``) has
somewhere to query (returning an empty set honestly, not a fabricated one).

``isolated_channels``/``substituted_channels`` are Doc05 ``TEXT[]`` — stored
here as a portable ``JSON`` list of strings (identical data, SQLite-testable)
rather than a Postgres-only ``ARRAY`` type; this is a storage-representation
choice only, not a schema meaning change.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.schemas.contracts import Attribution, HealthState, RLAction


class Decision(Base):
    __tablename__ = "decisions"

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    anomaly_flag: Mapped[bool | None] = mapped_column(Boolean)
    anomaly_severity: Mapped[float | None] = mapped_column(Float)
    attribution: Mapped[Attribution | None] = mapped_column(Enum(Attribution, name="attribution"))
    reason: Mapped[str | None] = mapped_column(String)
    trust_temperature: Mapped[float | None] = mapped_column(Float)
    trust_vibration: Mapped[float | None] = mapped_column(Float)
    trust_pressure: Mapped[float | None] = mapped_column(Float)
    trust_humidity: Mapped[float | None] = mapped_column(Float)
    trust_gas: Mapped[float | None] = mapped_column(Float)
    trust_current: Mapped[float | None] = mapped_column(Float)
    health_state: Mapped[HealthState | None] = mapped_column(Enum(HealthState, name="health_state"))
    failure_eta: Mapped[float | None] = mapped_column(Float)
    rl_action: Mapped[RLAction | None] = mapped_column(Enum(RLAction, name="rl_action"))
    isolated_channels: Mapped[list[str] | None] = mapped_column(JSON)
    substituted_channels: Mapped[list[str] | None] = mapped_column(JSON)
