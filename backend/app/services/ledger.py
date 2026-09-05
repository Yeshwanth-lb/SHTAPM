"""Tamper-evident ledger — SHA-256 hash chain (P4-M5 · D004, Doc05 §05.2
``ledger_blocks``).

``this_hash = sha256(block_index + ts + payload_hash + prev_hash)`` — D004's
formula literally. ``payload_hash`` is sha256 of the payload's canonical
JSON form (keys sorted, no whitespace) — Doc05 specifies no payload
serialization; this is a documented, deterministic project-local choice.
Genesis (``block_index`` 0) uses ``GENESIS_PREV_HASH`` (64 zero characters,
a sha256 hex digest's length) — Doc05 names no genesis value either; this
is the conventional choice, applied consistently by both ``append`` and
``verify``.

``_ts_for_hash`` normalizes a timestamp to UTC before formatting: SQLite
(used in this project's hardware/DB-free unit tests) silently drops
``tzinfo`` on round-trip while preserving the wall-clock value — without
this normalization, ``verify()`` recomputing a hash from a DB-read
timestamp would produce a different string than ``append()`` used at
write time and falsely report tampering. Postgres's ``TIMESTAMPTZ``
doesn't have this problem, but normalizing costs nothing there either.

Scope: this chains device-scoped, safety-relevant events — Doc05's own
``event_type`` examples ("trust_drop","isolate","safe_stop") plus admin
threshold edits ("config_update") added by this module. It deliberately
does NOT duplicate RBAC-denial auditing: Doc05's own ``audit_log.action``
example list already names ``"rbac_denied"`` there (not in
``ledger_blocks``), and most RBAC-checked endpoints (e.g. ``/api/users``)
have no device to chain against at all.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import LedgerBlock

GENESIS_PREV_HASH = "0" * 64


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _ts_for_hash(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).isoformat()


def _sha256_hex(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
    return h.hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    broken_at: int | None


def append(db: Session, *, device_id: uuid.UUID, event_type: str, payload: dict) -> LedgerBlock:
    last = (
        db.query(LedgerBlock)
        .filter(LedgerBlock.device_id == device_id)
        .order_by(LedgerBlock.block_index.desc())
        .first()
    )
    block_index = 0 if last is None else last.block_index + 1
    prev_hash = GENESIS_PREV_HASH if last is None else last.this_hash

    ts = datetime.now(UTC)
    payload_hash = _sha256_hex(_canonical_json(payload))
    this_hash = _sha256_hex(str(block_index), _ts_for_hash(ts), payload_hash, prev_hash)

    block = LedgerBlock(
        device_id=device_id,
        block_index=block_index,
        ts=ts,
        event_type=event_type,
        payload=payload,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        this_hash=this_hash,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def verify(db: Session, device_id: uuid.UUID) -> VerifyResult:
    blocks = (
        db.query(LedgerBlock)
        .filter(LedgerBlock.device_id == device_id)
        .order_by(LedgerBlock.block_index)
        .all()
    )
    expected_prev = GENESIS_PREV_HASH
    for block in blocks:
        expected_payload_hash = _sha256_hex(_canonical_json(block.payload))
        if block.payload_hash != expected_payload_hash:
            return VerifyResult(valid=False, broken_at=block.block_index)
        if block.prev_hash != expected_prev:
            return VerifyResult(valid=False, broken_at=block.block_index)
        expected_this_hash = _sha256_hex(
            str(block.block_index), _ts_for_hash(block.ts), block.payload_hash, block.prev_hash
        )
        if block.this_hash != expected_this_hash:
            return VerifyResult(valid=False, broken_at=block.block_index)
        expected_prev = block.this_hash
    return VerifyResult(valid=True, broken_at=None)
