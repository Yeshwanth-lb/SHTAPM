"""Raise operator alerts at the moments the ledger records an incident (D053).

``alerts`` (Doc05 §05.3) had an API with acknowledge, but no producer, so the
Alerts page was always empty -- while trust drops, Safe Pump-Stops and dead
sensors were already being chained into the ledger. An alert is raised at
exactly those edge-triggered moments, by the same services, so one incident is
one alert (never one per 1 Hz cycle):

  trust_drop   critical; ``attack`` / ``fault`` from the edge's attribution of
               that channel in the same decision, ``system`` when the edge
               attributed nothing (trust collapsed without an explanation)
  safe_stop    critical ``system``: the pump was stopped autonomously
  sensor_dead  warning ``fault``: a sensor stopped answering (D045)

Recoveries do not raise alerts: they are what acknowledgement is for, and they
stay visible in the ledger. Failure here never blocks the ledger write that
triggered it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Alert
from app.models.enums import AlertSeverity, AlertType

log = logging.getLogger("shtapm.services.alerts")


def raise_alert(
    db: Session,
    *,
    device_id: uuid.UUID,
    severity: AlertSeverity,
    type: AlertType,  # noqa: A002 -- the Doc05 column name
    message: str,
    channel: str | None = None,
    reason: str | None = None,
) -> None:
    try:
        db.add(
            Alert(
                device_id=device_id,
                ts=datetime.now(UTC),
                severity=severity,
                type=type,
                channel=channel,
                message=message,
                reason=reason,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        log.warning("alert write failed", exc_info=False)


def trust_drop_alert(
    db: Session, device_id: uuid.UUID, channel: str, attribution: str, reason: str, trust
) -> None:
    trust_text = f" (trust {trust:.2f})" if isinstance(trust, int | float) else ""
    if attribution == "attack":
        kind, text = AlertType.attack, f"Attack on {channel}: trust below 0.40{trust_text}"
    elif attribution == "fault":
        kind, text = AlertType.fault, f"Fault on {channel}: trust below 0.40{trust_text}"
    else:
        kind, text = AlertType.system, f"Trust on {channel} fell below 0.40{trust_text}"
    raise_alert(
        db,
        device_id=device_id,
        severity=AlertSeverity.critical,
        type=kind,
        channel=channel,
        message=text,
        reason=reason or None,
    )
