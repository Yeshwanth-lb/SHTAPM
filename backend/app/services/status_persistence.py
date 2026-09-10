"""Persist device online/offline status from the MQTT LWT topic.

Writes ONLY ``devices.status``. In particular it does NOT touch
``last_seen_at``: that means "when telemetry last arrived" and is owned by
``TelemetryPersistence``. A retained ``offline`` delivered on backend startup
would otherwise rewrite a perfectly good last-seen timestamp with the moment
the backend happened to reconnect, which is a different fact entirely.

The device row is created if absent, mirroring
``TelemetryPersistence._ensure_device``: status can legitimately arrive before
the first telemetry frame (the publisher sends retained ``online`` at connect,
before the first 1 Hz tick).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.models import Device
from app.models.enums import DeviceStatus

log = logging.getLogger("shtapm.status_persistence")

# The wire strings the edge publishes -> the stored enum. `degraded` exists in
# the schema but the edge never publishes it, so nothing maps to it here.
_WIRE_TO_STATUS = {
    "online": DeviceStatus.online,
    "offline": DeviceStatus.offline,
}


class StatusPersistence:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._device_uuid_cache: dict[str, uuid.UUID] = {}

    def persist(self, device_id: str, status: str) -> None:
        """Sink signature matches ``StatusConsumer``'s ``StatusSink``."""
        mapped = _WIRE_TO_STATUS.get(status)
        if mapped is None:
            # The consumer already rejects unknown payloads; this is a second
            # gate so a future caller cannot write an arbitrary status.
            log.warning("ignoring unmapped status %r for %s", status, device_id)
            return

        with self._session_factory() as db:
            device_uuid = self._ensure_device(db, device_id)
            device = db.get(Device, device_uuid)
            if device.status != mapped:
                log.info("device %s status %s -> %s", device_id, device.status.value, mapped.value)
            device.status = mapped
            db.commit()

    def _ensure_device(self, db: Session, device_id: str) -> uuid.UUID:
        cached = self._device_uuid_cache.get(device_id)
        if cached is not None:
            return cached
        device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is None:
            device = Device(device_id=device_id, name=device_id)
            db.add(device)
            db.commit()
            db.refresh(device)
        self._device_uuid_cache[device_id] = device.id
        return device.id
