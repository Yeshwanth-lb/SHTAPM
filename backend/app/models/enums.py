"""DB-only enums (P4 · Doc05 §05.2).

Deliberately separate from ``app.schemas.contracts`` for concepts Doc05 owns
that the wire contract never mentions (``UserRole``, ``DeviceStatus``,
``AlertSeverity``, ``AlertType``) — a persistence-layer vocabulary, not a
wire one.

Where a DB column's value set is IDENTICAL to an existing frozen wire enum
(``Attribution``, ``HealthState``, ``RLAction``, ``Channel``), the model
modules import and reuse that enum directly instead of redefining it — Doc05
§05.8 itself notes these are the same vocabulary, just a different column
name at rest (e.g. wire ``health`` → column ``health_state``).
"""

from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    operator = "operator"
    analyst = "analyst"
    admin = "admin"


class DeviceStatus(str, Enum):
    online = "online"
    offline = "offline"
    degraded = "degraded"


class AlertSeverity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class AlertType(str, Enum):
    fault = "fault"
    attack = "attack"
    system = "system"
