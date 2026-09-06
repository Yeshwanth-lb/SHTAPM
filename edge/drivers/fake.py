"""Fake ``RawRead`` sources for hardware-free tests/dev (P1 · C1). No hardware.

These feed the real ``Sensor`` so tests exercise the actual calibration /
clamp / health logic — not a parallel fake implementation.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping

from app.schemas.contracts import CHANNELS

from edge.drivers.base import Clock, RawRead, Sensor, SensorDriver, now_iso_ms


def constant_raw(value: float) -> RawRead:
    """Always returns ``value``."""

    def _read() -> float:
        return value

    return _read


# Fraction of the current drift-from-baseline pulled back toward baseline on
# each realistic_raw() call. An internal engineering constant (not exposed
# to callers, not a sensor spec): without it, an unbounded random walk would
# eventually wander far past any Sensor value_range, saturate against the
# clamp, and read as a falsely "frozen" value forever (exactly the failure
# mode staleness detection exists to catch) instead of hovering realistically
# around ``baseline``.
_DRIFT_MEAN_REVERSION_FIXTURE = 0.02


def realistic_raw(
    *,
    baseline: float,
    noise_std: float,
    drift_std: float,
    seed: int,
) -> RawRead:
    """Deterministic, reproducible, time-varying signal for hardware-free
    "realistic" fake sensors — NOT a physical model, NOT a validation claim,
    NOT calibrated against any real sensor. It exists so P2 (trust/
    consistency/correlation) has something other than a flat constant to
    observe on hardware-free channels; see registry.py's
    ``_REALISTIC_FAKE_PARAMS_FIXTURE`` for this project's own illustrative
    per-channel starting points.

    Composition (a discrete, mean-reverting random walk plus independent
    per-sample noise):
      - a slow-moving "level" that starts at ``baseline`` and each call
        drifts by a Gaussian step (``drift_std``), pulled back toward
        ``baseline`` by a small fixed fraction each step so it hovers
        rather than wandering unboundedly (see
        ``_DRIFT_MEAN_REVERSION_FIXTURE``) — this gives gradual drift with
        temporal continuity (consecutive reads are correlated through the
        persisted level, not independent draws);
      - independent Gaussian noise (``noise_std``) added on top of the
        current level for each individual reading.

    Deterministic and reproducible: a ``random.Random(seed)`` instance is
    created once and advanced on every call — the same seed always produces
    the same sequence of values, with no wall-clock or global RNG state
    involved. ``seed`` has no default (consistent with this module's other
    "intentionally NOT invented here" parameters) — no arbitrary seed is
    chosen on a caller's behalf.

    Boundedness is deliberately NOT this function's job: pass ``value_range``
    to the ``Sensor``/``DriverSpec`` wrapping this raw_read (the same
    P1-ACQ-E2 clamp mechanism every real driver already uses), rather than
    duplicating clamping logic here.
    """
    if noise_std < 0.0 or drift_std < 0.0:
        raise ValueError("noise_std and drift_std must both be >= 0")
    rng = random.Random(seed)
    state = {"level": baseline}

    def _read() -> float:
        drift_from_baseline = state["level"] - baseline
        state["level"] = (
            baseline
            + drift_from_baseline * (1.0 - _DRIFT_MEAN_REVERSION_FIXTURE)
            + rng.gauss(0.0, drift_std)
        )
        return state["level"] + rng.gauss(0.0, noise_std)

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
