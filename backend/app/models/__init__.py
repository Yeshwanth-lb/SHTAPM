"""SHTAPM ORM models (P4 · Doc05 §05.2).

Importing this package registers every table on ``Base.metadata`` — required
for Alembic autogenerate and for ``Base.metadata.create_all()`` in tests.
"""

from __future__ import annotations

from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.decision import Decision
from app.models.device import Device, Sensor
from app.models.ledger import LedgerBlock
from app.models.refresh_token import RefreshToken
from app.models.telemetry import SensorReading
from app.models.threshold import Threshold
from app.models.user import User

__all__ = [
    "Alert",
    "AuditLog",
    "Base",
    "Decision",
    "Device",
    "LedgerBlock",
    "RefreshToken",
    "Sensor",
    "SensorReading",
    "Threshold",
    "User",
]
