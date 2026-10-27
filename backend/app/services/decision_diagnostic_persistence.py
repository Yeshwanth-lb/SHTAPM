"""Decision-diagnostic → ``decisions`` persistence sink.

Registered on ``DecisionDiagnosticConsumer.add_sink()`` — a wholly separate
consumer/subscription from telemetry (see
``app.mqtt.decision_diagnostic_consumer``'s own docstring), so this sink can
never affect telemetry ingestion or persistence.

Reuses the EXISTING ``decisions`` table (``app.models.decision.Decision``)
and its already-nullable columns — no schema change, no new table. Persists
the fields this diagnostic payload genuinely carries: ``anomaly_flag``,
``anomaly_severity``, the six per-channel trust scores,
``substituted_channels`` (twin reconstructions), and (D042):

``isolated_channels``  the edge's tracked isolation set -- the channels the
                       edge currently isolates, substitutes for, and chains
                       ``isolate``/``recover`` ledger blocks about.
``attribution``        one decision-level label from the per-channel ones,
                       by severity: ``attack`` if any channel is attributed an
                       attack, else ``fault`` if any channel a fault, else
                       ``none`` (a security incident outranks a fault, which
                       outranks nothing). ``reason`` names the channel(s)
                       carrying that label with the edge's own reason, so the
                       reduction never hides WHICH sensor or WHY.

``health_state``, ``failure_eta`` and ``rl_action`` stay ``NULL``: nothing
computes them (no prognosis model, no RL policy), and a value would be
invented.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Decision, Device
from app.schemas.contracts import Attribution
from app.schemas.decision_diagnostic import DecisionDiagnosticMessage

log = logging.getLogger("shtapm.decision_diagnostic_persistence")


_SEVERITY = (Attribution.attack, Attribution.fault)


def reduce_attribution(message: DecisionDiagnosticMessage) -> tuple[Attribution, str | None]:
    """attack > fault > none over the per-channel labels (D042), with the
    channel(s) and the edge's reasons for the winning label."""
    for label in _SEVERITY:
        hits = [
            f"{_channel_name(channel)}: {verdict.reason}"
            for channel, verdict in message.attribution.items()
            if verdict.attribution == label
        ]
        if hits:
            return label, "; ".join(sorted(hits))
    return Attribution.none, None


def _channel_name(channel: object) -> str:
    return getattr(channel, "value", str(channel))


class DecisionDiagnosticPersistence:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._device_uuid_cache: dict[str, uuid.UUID] = {}

    def persist(self, message: DecisionDiagnosticMessage) -> None:
        """Sink signature matches ``DecisionDiagnosticConsumer``'s
        ``DecisionDiagnosticSink``. See module docstring for exactly which
        columns get a value and which stay ``NULL``."""
        ts = datetime.fromisoformat(message.ts)
        attribution, reason = reduce_attribution(message)
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
                    attribution=attribution,
                    reason=reason,
                    isolated_channels=[
                        _channel_name(c) for c in message.tracked_isolation_candidates
                    ],
                    # Real executed substitutions (FR-H1/FR-H2). Unlike the
                    # NULL columns above, this one now has a genuine producer:
                    # the edge's trained digital twin. Written as [] rather
                    # than NULL when nothing was substituted, so "no twin ran"
                    # (NULL, older rows) stays distinguishable from "a twin ran
                    # and substituted nothing".
                    substituted_channels=list(message.substituted_channels),
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
