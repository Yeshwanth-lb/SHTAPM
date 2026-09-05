"""``ledger_blocks`` table (Doc05 §05.2) — SHA-256 hash chain (D004).

``payload`` is Doc05 ``JSONB`` — stored here as portable ``JSON`` (SQLite-
testable; identical semantics on Postgres). The chain-computation and
verification logic lives in ``app.services.ledger``, not here — this module
is schema only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import UUIDPk


class LedgerBlock(Base):
    __tablename__ = "ledger_blocks"
    __table_args__ = (
        UniqueConstraint("device_id", "block_index", name="uq_ledger_blocks_device_index"),
    )

    id: Mapped[UUIDPk]
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    block_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    this_hash: Mapped[str] = mapped_column(String, nullable=False)
