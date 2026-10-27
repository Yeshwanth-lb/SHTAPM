"""Dead sensors on the backend (D045): latest stale set per device + the ledger.

The edge reports ``stale_channels`` -- sensors that stopped responding and are
publishing their last good reading -- on every decision message.

``SensorHealthRegistry``  newest stale set per device and when each sensor went
                          stale (first seen), read by
                          ``GET /api/devices/{id}/sensor-health``.
``SensorHealthLedger``    chains ``sensor_dead`` / ``sensor_recovered`` on each
                          transition into the tamper-evident ledger (AC5).
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Device
from app.schemas.decision_diagnostic import DecisionDiagnosticMessage
from app.services import ledger as ledger_service

log = logging.getLogger("shtapm.services.sensor_health")

EVENT_SENSOR_DEAD = "sensor_dead"
EVENT_SENSOR_RECOVERED = "sensor_recovered"


def _names(message: DecisionDiagnosticMessage) -> set[str]:
    return {getattr(c, "value", str(c)) for c in message.stale_channels}


class SensorHealthRegistry:
    def __init__(self) -> None:
        self._since: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def update(self, message: DecisionDiagnosticMessage) -> None:
        stale = _names(message)
        with self._lock:
            current = self._since.setdefault(message.device_id, {})
            for ch in stale - set(current):
                current[ch] = message.ts
            for ch in set(current) - stale:
                del current[ch]

    def get(self, device_id: str) -> dict[str, str]:
        """channel -> ISO timestamp of the first decision that reported it stale."""
        with self._lock:
            return dict(self._since.get(device_id, {}))


class SensorHealthLedger:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._stale: dict[str, set[str]] = {}

    def record(self, message: DecisionDiagnosticMessage) -> None:
        stale = _names(message)
        before = self._stale.get(message.device_id, set())
        died, recovered = stale - before, before - stale
        if not died and not recovered:
            return
        try:
            with self._session_factory() as db:
                device = db.scalar(select(Device).where(Device.device_id == message.device_id))
                if device is None:
                    return
                transitions = ((EVENT_SENSOR_DEAD, died), (EVENT_SENSOR_RECOVERED, recovered))
                for event, channels in transitions:
                    for ch in sorted(channels):
                        ledger_service.append(
                            db,
                            device_id=device.id,
                            event_type=event,
                            payload={"channel": ch, "ts": message.ts},
                        )
            self._stale[message.device_id] = stale
        except Exception:
            log.warning("sensor health ledger write failed", exc_info=False)
