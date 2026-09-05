"""Privileged-action audit trail (P4 · Doc05 §05.2 ``audit_log``).

Every RBAC denial and admin config change is written here (PRD's own
auditing requirement — "All privileged actions ... are themselves logged").
Ledger-chain entries (a narrower, tamper-evident subset — trust drops,
isolate, safe_stop) are separate (``app.services.ledger``, P4-M5); this
module is the plain audit trail, not the hash chain.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    *,
    user_id: uuid.UUID,
    action: str,
    target: str | None = None,
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(user_id=user_id, action=action, target=target, detail=detail)
    db.add(entry)
    db.commit()
    return entry
