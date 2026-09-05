"""``sensor_readings`` table (Doc05 §05.2) — TimescaleDB hypertable in prod.

Composite PK ``(device_id, ts, sample_seq)``, no surrogate ``id`` — Doc05
§05.1 notes hypertables are the exception to the "every table has a UUID id"
rule. The hypertable conversion itself (``create_hypertable``) is a
Postgres-only migration step (see ``alembic/versions/0001_initial_schema.py``)
— this model just declares the plain table shape, portable to SQLite for
unit tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    sample_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    vibration: Mapped[float] = mapped_column(Float, nullable=False)
    pressure: Mapped[float] = mapped_column(Float, nullable=False)
    humidity: Mapped[float] = mapped_column(Float, nullable=False)
    gas: Mapped[float] = mapped_column(Float, nullable=False)
    current: Mapped[float] = mapped_column(Float, nullable=False)
    healthy_mask: Mapped[int] = mapped_column(Integer, nullable=False)
