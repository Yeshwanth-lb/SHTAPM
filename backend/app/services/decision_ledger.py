"""Chain safety-relevant decision events into the tamper-evident ledger (AC5).

``ledger_blocks`` existed with a working append/verify service, but the only
producer was an admin threshold edit (``config_update``). Nothing from the
live decision path was ever chained, so "every decision is hash-chained"
(AC5) had no implementation behind it.

EDGE-TRIGGERED, NOT LEVEL-TRIGGERED. A block is appended when a channel ENTERS
a state, never for every cycle it remains in it. At 1 Hz, chaining each decision
row would produce ~86,400 blocks per device per day and bury the events an
auditor is looking for in steady-state noise. This matches the ledger service's
own stated scope -- "device-scoped, safety-relevant events" -- rather than a
literal reading of AC5 as one block per telemetry frame.

Events chained, both from Doc05's own ``event_type`` example list:

  ``trust_drop``  a channel's trust first falls into the MALICIOUS band, as
                  determined by the EDGE (this service never re-derives the
                  band boundary: it reads ``isolation_candidates``, which
                  edge/pipeline/isolation_fallback.py computes from the frozen
                  TRUSTED_MIN/MALICIOUS_MAX). Keeping that decision in one
                  place stops the backend and edge disagreeing about what
                  "malicious" means.

  ``isolate``     the digital twin first substitutes for a channel -- the
                  point at which the system ACTS on isolation rather than
                  merely observing it.

``safe_stop`` is deliberately absent: no actuation is wired in this build, so
there is no such event to chain. Adding it speculatively would put an event in
an audit record that cannot occur.

STATE IS PER-PROCESS. Transition tracking lives in memory, so a backend restart
can re-chain a still-active condition once. That is a visible duplicate in the
audit trail rather than a silent gap, which is the safer direction for a
tamper-evident record -- and it never invalidates the chain, since every block
is appended through the same ``ledger.append``.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.models import Device
from app.schemas.decision_diagnostic import DecisionDiagnosticMessage
from app.services import ledger as ledger_service

log = logging.getLogger("shtapm.decision_ledger")

EVENT_TRUST_DROP = "trust_drop"
EVENT_ISOLATE = "isolate"


def _channel_name(channel: object) -> str:
    """Plain channel name from a Channel enum member or a bare string."""
    return channel.value if hasattr(channel, "value") else str(channel)


class DecisionLedgerRecorder:
    """Appends a ledger block when a channel enters a safety-relevant state."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._device_uuid_cache: dict[str, uuid.UUID] = {}
        # device_id -> channels currently in each state, so a block is written
        # on entry only.
        self._trust_dropped: dict[str, set[str]] = {}
        self._substituted: dict[str, set[str]] = {}

    def record(self, message: DecisionDiagnosticMessage) -> None:
        """Sink signature matches ``DecisionDiagnosticConsumer``'s sink.

        Never raises: a ledger fault must not stop decision ingestion, which is
        the same best-effort posture the rest of this consumer's sinks hold.
        """
        try:
            self._record(message)
        except Exception:
            log.exception("failed to chain decision events for %s", message.device_id)

    def _record(self, message: DecisionDiagnosticMessage) -> None:
        device_id = message.device_id
        # `.value`, not `str()`: Channel is a str-Enum and str(Channel.current)
        # renders as "Channel.current", which would write a corrupted channel
        # name into a tamper-evident audit record. Same accessor the seed and
        # persistence layers use.
        candidates = {_channel_name(c) for c in message.isolation_candidates}
        substituted = {_channel_name(c) for c in message.substituted_channels}

        newly_dropped = candidates - self._trust_dropped.get(device_id, set())
        newly_substituted = substituted - self._substituted.get(device_id, set())

        # A channel that recovers must be able to trigger a NEW block if it
        # degrades again, so state tracks the CURRENT set rather than
        # accumulating every channel ever seen.
        self._trust_dropped[device_id] = candidates
        self._substituted[device_id] = substituted

        if not newly_dropped and not newly_substituted:
            return

        with self._session_factory() as db:
            device_uuid = self._ensure_device(db, device_id)
            for channel in sorted(newly_dropped):
                self._append(
                    db,
                    device_uuid,
                    EVENT_TRUST_DROP,
                    {
                        "channel": channel,
                        "trust": getattr(message.trust, channel, None),
                        "ts": message.ts,
                        "sample_seq": message.sample_seq,
                        "anomaly_flag": message.anomaly_flag,
                        "anomaly_severity": message.anomaly_severity,
                    },
                )
            for channel in sorted(newly_substituted):
                self._append(
                    db,
                    device_uuid,
                    EVENT_ISOLATE,
                    {
                        "channel": channel,
                        "action": "twin_substitution_started",
                        "ts": message.ts,
                        "sample_seq": message.sample_seq,
                        # The substituted VALUE is deliberately absent: it is not
                        # on this wire payload, and the ledger records that an
                        # action occurred, not the reconstruction itself.
                    },
                )
            db.commit()

    def _append(self, db: Session, device_uuid: uuid.UUID, event_type: str, payload: dict) -> None:
        ledger_service.append(db, device_id=device_uuid, event_type=event_type, payload=payload)
        log.info(
            "ledger: %s chained for device=%s channel=%s",
            event_type,
            payload.get("ts"),
            payload.get("channel"),
        )

    def _ensure_device(self, db: Session, device_id: str) -> uuid.UUID:
        """Same auto-registration pattern as the telemetry/decision sinks."""
        cached = self._device_uuid_cache.get(device_id)
        if cached is not None:
            return cached
        device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is None:
            device = Device(device_id=device_id, name=device_id)
            db.add(device)
            db.flush()
        self._device_uuid_cache[device_id] = device.id
        return device.id
