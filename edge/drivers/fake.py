"""Fake ``RawRead`` sources for hardware-free tests/dev (P1 · C1). No hardware.

These feed the real ``Sensor`` so tests exercise the actual calibration /
clamp / health logic — not a parallel fake implementation.
"""

from __future__ import annotations

from collections.abc import Iterable

from edge.drivers.base import RawRead


def constant_raw(value: float) -> RawRead:
    """Always returns ``value``."""

    def _read() -> float:
        return value

    return _read


def scripted_raw(values: Iterable) -> RawRead:
    """Return successive items; an ``Exception`` instance is raised, ``None`` is
    passed through (→ unhealthy). After the last item, the last item repeats."""
    items = list(values)
    state = {"i": 0}

    def _read():
        i = state["i"]
        state["i"] = i + 1
        item = items[i] if i < len(items) else items[-1]
        if isinstance(item, Exception):
            raise item
        return item

    return _read
