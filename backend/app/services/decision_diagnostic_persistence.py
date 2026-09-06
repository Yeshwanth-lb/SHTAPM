"""Decision-diagnostic → ``decisions`` persistence sink.

Registered on ``DecisionDiagnosticConsumer.add_sink()`` — a wholly separate
consumer/subscription from telemetry (see
``app.mqtt.decision_diagnostic_consumer``'s own docstring), so this sink can
never affect telemetry ingestion or persistence.

Reuses the EXISTING ``decisions`` table (``app.models.decision.Decision``)
and its already-nullable columns — no schema change, no new table. Persists
ONLY the fields genuinely compatible with this diagnostic payload:
``anomaly_flag``, ``anomaly_severity``, and the six per-channel trust
scores. ``health_state``, ``failure_eta``, ``rl_action``,
``isolated_channels``, and ``substituted_channels`` are left ``NULL`` —
nothing in this diagnostic payload maps to them without inventing a value
(see ``app/schemas/decision_diagnostic.py``'s own docstring for why those
fields don't exist on the wire payload at all). ``attribution``/``reason``
are ALSO left ``NULL`` here: the diagnostic payload carries a genuine
per-channel attribution, but ``decisions.attribution``/``reason`` are
single-value columns with no existing, non-invented reduction rule to a
single value — approved scope is to preserve the full per-channel
attribution on the wire only, not to persist it into these columns.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Decision, Device
from app.schemas.decision_diagnostic import DecisionDiagnosticMessage

log = logging.getLogger("shtapm.decision_diagnostic_persistence")


class DecisionDiagnosticPersistence:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._device_uuid_cache: dict[str, uuid.UUID] = {}

    def persist(self, message: DecisionDiagnosticMessage) -> None:
        """Sink signature matches ``DecisionDiagnosticConsumer``'s
        ``DecisionDiagnosticSink``. See module docstring for exactly which
        columns get a value and which stay ``NULL``."""
        ts = datetime.fromisoformat(message.ts)
        with self._session_factory() as db:
            device_uuid = self._ensure_device(db, message.device_id)
            db.add(
                Decision(
                    device_id=device_uuid,
                    ts=ts,
                    anomaly_flag=message.anomaly_flag,
                    anomaly_severity=message.anomaly_severity,
                    trust_temperature=message.trust.temperature,
                    trust_vibration=message.trust.vibration,
                    trust_pressure=message.trust.pressure,
                    trust_humidity=message.trust.humidity,
                    trust_gas=message.trust.gas,
                    trust_current=message.trust.current,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                log.info(
                    "duplicate decisions row skipped (device=%s ts=%s)",
                    message.device_id,
                    message.ts,
                )

    def _ensure_device(self, db: Session, device_id: str) -> uuid.UUID:
        """Same auto-registration pattern as
        ``TelemetryPersistence._ensure_device`` — a decision_diagnostic
        message should always arrive for an already-telemetry-registered
        device in practice, but this sink makes no such ordering assumption."""
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
