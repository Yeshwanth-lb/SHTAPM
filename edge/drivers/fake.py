"""Fake ``RawRead`` sources for hardware-free tests/dev (P1 · C1). No hardware.

These feed the real ``Sensor`` so tests exercise the actual calibration /
clamp / health logic — not a parallel fake implementation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from app.schemas.contracts import CHANNELS

from edge.drivers.base import Clock, RawRead, Sensor, SensorDriver, now_iso_ms


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


def fake_drivers(
    values: Mapping[str, float],
    *,
    units: Mapping[str, str] | None = None,
    clock: Clock = now_iso_ms,
) -> dict[str, SensorDriver]:
    """Build one healthy fake ``Sensor`` per frozen channel (hardware-free).

    ``values`` must cover exactly the six frozen channels. Each driver returns a
    constant value; ``units`` are cosmetic (units are not carried on the frozen
    wire frame). Real GPIO/I2C drivers are NOT implemented (hardware-blocked).
    """
    missing = set(CHANNELS) - set(values)
    extra = set(values) - set(CHANNELS)
    if missing or extra:
        raise ValueError(
            "values must cover exactly the frozen channels; "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    units = units or {}
    return {
        channel: Sensor(
            unit=units.get(channel, ""),
            raw_read=constant_raw(values[channel]),
            clock=clock,
        )
        for channel in CHANNELS
    }
