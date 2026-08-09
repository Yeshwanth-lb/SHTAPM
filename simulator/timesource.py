"""Wall-clock timestamp helper for the simulator's live (I/O) paths.

Kept out of generator.py so the generator stays pure/deterministic. Produces an
ISO-8601 UTC timestamp with millisecond precision and a trailing ``Z`` (FR-Q2).
"""

from __future__ import annotations

from datetime import UTC, datetime


def now_iso_ms() -> str:
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
