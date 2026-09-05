"""``devices`` + ``sensors`` tables (Doc05 §05.2).

``Device.health_state`` and ``Sensor.channel`` reuse the frozen wire enums
(``HealthState``, ``Channel``) rather than redefining equivalent values, per
D006/D007 (shared contract used verbatim everywhere a concept matches).
``Device.status`` has no wire-contract equivalent (not in
``app.schemas.contracts`` — ``device_status`` WS frames carry a free string
per Doc05 §05.8) so it uses the DB-only ``DeviceStatus`` enum.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import DeviceStatus
from app.models.types import UUIDPk
from app.schemas.contracts import Channel, HealthState


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[UUIDPk]
    device_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str | None] = mapped_column(String)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, name="device_status"), default=DeviceStatus.offline, nullable=False
    )
    health_state: Mapped[HealthState] = mapped_column(
        Enum(HealthState, name="health_state"), default=HealthState.healthy, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_rate_hz: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped[User | None] = relationship(back_populates="devices")  # noqa: F821
    sensors: Mapped[list[Sensor]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class Sensor(Base):
    __tablename__ = "sensors"
    __table_args__ = (UniqueConstraint("device_id", "channel", name="uq_sensors_device_channel"),)

    id: Mapped[UUIDPk]
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    channel: Mapped[Channel] = mapped_column(Enum(Channel, name="channel"), nullable=False)
    part: Mapped[str | None] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_hue: Mapped[str | None] = mapped_column(String)

    device: Mapped[Device] = relationship(back_populates="sensors")
