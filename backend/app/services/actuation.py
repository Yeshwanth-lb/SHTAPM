"""Relay state on the backend (D041): latest status per device, and the ledger.

``ActuationRegistry``        the newest ``ActuationStatus`` per device, read by
                             ``GET /api/devices/{id}/relay``. Thread-safe: the
                             MQTT thread writes, API threads read.
``ActuationLedgerRecorder``  chains every relay transition into the
                             tamper-evident ledger (AC5): ``safe_stop`` for an
                             autonomous stop (self-heal, dry-run, watchdog),
                             ``relay_on`` / ``relay_off`` otherwise. A retained
                             status re-delivered after a reconnect is the same
                             status (same edge timestamp) and is not chained twice.
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Device
from app.schemas.actuation import AUTONOMOUS_CAUSES, ActuationStatus
from app.services import ledger as ledger_service

log = logging.getLogger("shtapm.services.actuation")

EVENT_SAFE_STOP = "safe_stop"
EVENT_RELAY_ON = "relay_on"
EVENT_RELAY_OFF = "relay_off"
EVENT_RELAY_COMMAND = "relay_command"


def event_type_for(status: ActuationStatus) -> str:
    if status.cause in AUTONOMOUS_CAUSES:
        return EVENT_SAFE_STOP
    return EVENT_RELAY_ON if status.relay == "on" else EVENT_RELAY_OFF


class ActuationRegistry:
    def __init__(self) -> None:
        self._latest: dict[str, ActuationStatus] = {}
        self._lock = threading.Lock()

    def update(self, status: ActuationStatus) -> None:
        with self._lock:
            self._latest[status.device_id] = status

    def get(self, device_id: str) -> ActuationStatus | None:
        with self._lock:
            return self._latest.get(device_id)


class ActuationLedgerRecorder:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._last: dict[str, tuple[str, str, str]] = {}

    def record(self, status: ActuationStatus) -> None:
        key = (status.ts, status.relay, status.cause)
        if self._last.get(status.device_id) == key:
            return  # the retained status, re-delivered
        try:
            with self._session_factory() as db:
                device = db.scalar(select(Device).where(Device.device_id == status.device_id))
                if device is None:
                    log.warning("actuation status for unknown device %s", status.device_id)
                    return
                ledger_service.append(
                    db,
                    device_id=device.id,
                    event_type=event_type_for(status),
                    payload=status.model_dump(mode="json"),
                )
            self._last[status.device_id] = key
        except Exception:
            log.warning("actuation ledger write failed", exc_info=False)
