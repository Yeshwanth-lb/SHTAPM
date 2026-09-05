"""Telemetry → ``sensor_readings`` persistence sink (P4-M3 · Doc06 P4 goal #2).

Registered via the existing ``TelemetryConsumer.add_sink()`` seam alongside
the WS broadcaster — persistence runs off the live-delivery hot path: this
sink is independent of, and cannot block or drop, a WS frame (the consumer
already isolates sink failures from each other and from ingestion itself).
One short-lived session per message, not a long-held one, so a failed
commit here can never poison a later write.

``healthy_mask``: the frozen wire contract carries NO per-channel health
(``edge/acquisition/sampler.py``'s ``sample_once`` only ever emits a frame
when ALL SIX channels are healthy — an unhealthy channel is never put on
the wire at all). Every persisted reading is therefore all-healthy by
construction; the mask is always ``0b111111``, not a fabricated per-channel
derivation from data that doesn't exist on the wire.

Device auto-registration: the frozen contract has no device-registration
message, so the first telemetry frame seen for a ``device_id`` creates a
minimal ``devices`` row (``name`` defaults to the device_id — an operator
can rename it later via the admin REST endpoint, P4-M4). A small in-memory
cache avoids a lookup query on every single sample.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Device, SensorReading
from app.schemas.contracts import TelemetryMessage

log = logging.getLogger("shtapm.telemetry_persistence")

ALL_CHANNELS_HEALTHY_MASK = 0b111111


class TelemetryPersistence:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._device_uuid_cache: dict[str, uuid.UUID] = {}

    def persist(self, message: TelemetryMessage) -> None:
        """Sink signature matches ``TelemetryConsumer``'s ``TelemetrySink``."""
        ts = datetime.fromisoformat(message.ts)
        with self._session_factory() as db:
            device_uuid = self._ensure_device(db, message.device_id)
            # Fetch + update the device BEFORE adding the reading: querying
            # after add() would autoflush the pending (possibly duplicate)
            # insert early, raising IntegrityError outside the try/except below.
            device = db.get(Device, device_uuid)
            device.last_seen_at = ts
            db.add(
                SensorReading(
                    device_id=device_uuid,
                    ts=ts,
                    sample_seq=message.sample_seq,
                    temperature=message.sensors.temperature,
                    vibration=message.sensors.vibration,
                    pressure=message.sensors.pressure,
                    humidity=message.sensors.humidity,
                    gas=message.sensors.gas,
                    current=message.sensors.current,
                    healthy_mask=ALL_CHANNELS_HEALTHY_MASK,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                log.info(
                    "duplicate sensor_readings row skipped (device=%s sample_seq=%s)",
                    message.device_id,
                    message.sample_seq,
                )

    def _ensure_device(self, db: Session, device_id: str) -> uuid.UUID:
        cached = self._device_uuid_cache.get(device_id)
        if cached is not None:
            return cached
        device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is None:
            device = Device(device_id=device_id, name=device_id)
            db.add(device)
            db.flush()  # assign device.id without committing yet
        self._device_uuid_cache[device_id] = device.id
        return device.id
