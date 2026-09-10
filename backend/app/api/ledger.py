"""``/api/ledger`` (P4-M5 · Doc05 §05.7).

Scoped like devices/alerts (Doc05 §05.6 app-level scoping): an analyst only
sees the ledger for devices they own; admin sees all. Doc05's REST table
doesn't spell out "(scoped)" for these three rows the way it does for
devices/alerts, but ledger blocks are device-scoped data by construction
(``ledger_blocks.device_id``), so the same ownership rule is applied here
for consistency rather than leaving it as an unscoped admin/analyst
free-for-all the rest of the schema doesn't otherwise allow.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import require_device_access, require_role
from app.core.db import get_db
from app.models import LedgerBlock, User
from app.models.enums import UserRole
from app.services.ledger import verify as verify_chain

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

_ALLOWED_ROLES = (UserRole.analyst, UserRole.admin)

# Bounded listing. Verification and export deliberately keep their own
# caps: a partially-listed chain is fine to READ, but a truncated export
# would look like a complete audit record and must be capped explicitly.
_MAX_LEDGER_LIMIT = 1000
_DEFAULT_LEDGER_LIMIT = 200


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LedgerBlockOut(_Body):
    block_index: int
    ts: datetime
    event_type: str
    payload: dict
    payload_hash: str
    prev_hash: str
    this_hash: str


class VerifyOut(_Body):
    valid: bool
    broken_at: int | None


def _to_block_out(block: LedgerBlock) -> LedgerBlockOut:
    return LedgerBlockOut(
        block_index=block.block_index,
        ts=block.ts,
        event_type=block.event_type,
        payload=block.payload,
        payload_hash=block.payload_hash,
        prev_hash=block.prev_hash,
        this_hash=block.this_hash,
    )


@router.get("/{device_id}", response_model=list[LedgerBlockOut])
def list_blocks(
    device_id: str,
    limit: int = Query(default=_DEFAULT_LEDGER_LIMIT, ge=1, le=_MAX_LEDGER_LIMIT),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ALLOWED_ROLES)),
) -> list[LedgerBlockOut]:
    """Most recent ``limit`` blocks, returned in ascending block order.

    Ascending order is preserved because a hash chain only reads correctly
    forwards — each block references its predecessor. Truncation therefore
    drops the OLDEST blocks, never breaking the contiguity of what is shown.
    Chain verification always walks the full chain server-side regardless of
    this limit, so a truncated view can never produce a false "valid".
    """
    device = require_device_access(db, user, device_id)
    rows = (
        db.query(LedgerBlock)
        .filter(LedgerBlock.device_id == device.id)
        .order_by(LedgerBlock.block_index.desc())
        .limit(limit)
        .all()
    )
    return [_to_block_out(b) for b in reversed(rows)]


@router.post("/{device_id}/verify", response_model=VerifyOut)
def verify_ledger(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ALLOWED_ROLES)),
) -> VerifyOut:
    device = require_device_access(db, user, device_id)
    result = verify_chain(db, device.id)
    return VerifyOut(valid=result.valid, broken_at=result.broken_at)


@router.get("/{device_id}/export")
def export_ledger(
    device_id: str,
    format: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ALLOWED_ROLES)),
):
    if format not in ("json", "csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "format must be 'json' or 'csv'")
    device = require_device_access(db, user, device_id)
    rows = (
        db.query(LedgerBlock)
        .filter(LedgerBlock.device_id == device.id)
        .order_by(LedgerBlock.block_index)
        .all()
    )
    blocks = [_to_block_out(b) for b in rows]

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["block_index", "ts", "event_type", "payload", "payload_hash", "prev_hash", "this_hash"]
        )
        for b in blocks:
            writer.writerow(
                [b.block_index, b.ts.isoformat(), b.event_type, b.payload, b.payload_hash,
                 b.prev_hash, b.this_hash]
            )
        return Response(content=buf.getvalue(), media_type="text/csv")

    return [b.model_dump(mode="json") for b in blocks]
