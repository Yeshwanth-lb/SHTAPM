"""``thresholds`` table (Doc05 §05.2) — per-device config, admin-writable.

``divergence_threshold`` has NO default here, matching the edge-side
convention (``edge/pipeline/divergence.py``): U05's numeric value is still
open (data-gated, per DECISIONS.md), so the column stays NULL until an
admin sets it explicitly — never silently defaulted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Threshold(Base):
    __tablename__ = "thresholds"

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    trust_trusted_min: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    trust_malicious_max: Mapped[float] = mapped_column(Float, default=0.4, nullable=False)
    trust_w_consistency: Mapped[float] = mapped_column(Float, default=0.4, nullable=False)
    trust_w_correlation: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
    trust_w_reliability: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
    window_size: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    substitution_max_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    divergence_threshold: Mapped[float | None] = mapped_column(Float)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
