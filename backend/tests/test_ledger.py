"""P4-M5 — ledger hash-chain service tests (D004, Doc05 §05.2 ledger_blocks)."""

from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")

from app.models import Base, Device, LedgerBlock  # noqa: E402
from app.services.ledger import GENESIS_PREV_HASH, append, verify  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def device_id(session_factory):
    with session_factory() as db:
        device = Device(device_id="pump-01", name="Pump 01")
        db.add(device)
        db.commit()
        db.refresh(device)
        return device.id


def test_append_creates_genesis_block(session_factory, device_id):
    with session_factory() as db:
        block = append(db, device_id=device_id, event_type="isolate", payload={"channel": "p"})
    assert block.block_index == 0
    assert block.prev_hash == GENESIS_PREV_HASH
    assert len(block.this_hash) == 64


def test_append_chains_blocks(session_factory, device_id):
    with session_factory() as db:
        first = append(db, device_id=device_id, event_type="isolate", payload={"a": 1})
        second = append(db, device_id=device_id, event_type="safe_stop", payload={"b": 2})
    assert second.block_index == 1
    assert second.prev_hash == first.this_hash
    assert second.this_hash != first.this_hash


def test_append_is_independent_per_device(session_factory, device_id):
    with session_factory() as db:
        other = Device(device_id="pump-02", name="Pump 02")
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id

        append(db, device_id=device_id, event_type="isolate", payload={})
        first_of_other = append(db, device_id=other_id, event_type="isolate", payload={})
    assert first_of_other.block_index == 0  # independent chain, not continuing pump-01's


def test_verify_empty_chain_is_valid(session_factory, device_id):
    with session_factory() as db:
        result = verify(db, device_id)
    assert result.valid is True
    assert result.broken_at is None


def test_verify_valid_chain(session_factory, device_id):
    with session_factory() as db:
        append(db, device_id=device_id, event_type="isolate", payload={"a": 1})
        append(db, device_id=device_id, event_type="safe_stop", payload={"b": 2})
        append(db, device_id=device_id, event_type="config_update", payload={"c": 3})

    # Fresh session — forces every field to be re-read from the DB, exercising
    # the exact SQLite tzinfo-round-trip path verify() must tolerate.
    with session_factory() as db2:
        result = verify(db2, device_id)
    assert result.valid is True
    assert result.broken_at is None


def test_verify_detects_tampered_payload(session_factory, device_id):
    with session_factory() as db:
        append(db, device_id=device_id, event_type="isolate", payload={"a": 1})
        second = append(db, device_id=device_id, event_type="safe_stop", payload={"b": 2})

    with session_factory() as db2:
        row = db2.get(LedgerBlock, second.id)
        row.payload = {"b": 999}  # tamper: payload changed, hashes left as-is
        db2.commit()

    with session_factory() as db3:
        result = verify(db3, device_id)
    assert result.valid is False
    assert result.broken_at == 1


def test_verify_detects_broken_chain_link(session_factory, device_id):
    with session_factory() as db:
        append(db, device_id=device_id, event_type="isolate", payload={"a": 1})
        second = append(db, device_id=device_id, event_type="safe_stop", payload={"b": 2})
        append(db, device_id=device_id, event_type="config_update", payload={"c": 3})

    with session_factory() as db2:
        row = db2.get(LedgerBlock, second.id)
        row.this_hash = "f" * 64  # tamper: breaks the link to block 2
        db2.commit()

    with session_factory() as db3:
        result = verify(db3, device_id)
    assert result.valid is False
    assert result.broken_at == 1  # block 1's own this_hash no longer matches its own content


def test_payload_canonicalization_is_key_order_independent(session_factory, device_id):
    with session_factory() as db:
        block = append(db, device_id=device_id, event_type="isolate", payload={"x": 1, "y": 2})

    with session_factory() as db2:
        row = db2.get(LedgerBlock, block.id)
        row.payload = {"y": 2, "x": 1}  # same content, different key order — not tampering
        db2.commit()

    with session_factory() as db3:
        result = verify(db3, device_id)
    assert result.valid is True
