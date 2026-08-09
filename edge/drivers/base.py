"""Edge sensor-driver interface + hardware-free logic (P1 · C1).

TRD §02.8 firmware discipline: each driver exposes
``read() -> {value, unit, ts, healthy}``; a failed read returns
``healthy=False`` and **never throws into the loop**.

This module holds ONLY the hardware-free core:
  * ``SensorDriver`` — the interface consumers depend on,
  * ``Sensor`` — a concrete driver wrapping a ``RawRead`` callable with
    calibration, range-clamping, health handling, and timestamping.

Real GPIO/I2C/SPI/1-Wire access is provided later as a ``RawRead`` callable
(e.g. reading an INA219 over I2C); consumers never change. No hardware here.

``value`` is ``None`` when the read is unhealthy; how an unhealthy channel is
represented in the frozen telemetry contract (impute / healthy_mask) is the
sampler's concern (C2), not the driver's.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

# Hardware-specific read; returns a raw numeric value or raises on failure.
RawRead = Callable[[], float]
# Raw → engineering-unit transform (e.g. lambda raw: raw * scale + offset).
Calibrate = Callable[[float], float]
# Clock returning an ISO-8601 UTC ms timestamp (injectable for deterministic tests).
Clock = Callable[[], str]


def now_iso_ms() -> str:
    """ISO-8601 UTC timestamp with millisecond precision + trailing ``Z`` (FR-Q2).

    Edge-local (the edge tier stays independent of the simulator, D003).
    """
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@dataclass(frozen=True)
class Reading:
    value: float | None  # None ⟺ unhealthy read
    unit: str
    ts: str
    healthy: bool

    def as_dict(self) -> dict:
        return asdict(self)


class SensorDriver(ABC):
    """Interface every driver (fake or real hardware) implements."""

    @abstractmethod
    def read(self) -> Reading: ...


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


class Sensor(SensorDriver):
    """Concrete driver: ``RawRead`` → calibrate → range-clamp → ``Reading``.

    - raw read raises / returns ``None`` / non-numeric / ``NaN`` → healthy=False,
      value=None (never raises).
    - numeric read → optional calibration, then optional clamp to ``value_range``
      (out-of-range is clamped, not treated as garbage — P1-ACQ-E2), healthy=True.

    ``calibrate`` and ``value_range`` are per-sensor and supplied by the caller
    (defaults: identity / no clamp). They are intentionally NOT invented here;
    real per-sensor values arrive with the hardware drivers / config.
    """

    def __init__(
        self,
        *,
        unit: str,
        raw_read: RawRead,
        calibrate: Calibrate | None = None,
        value_range: tuple[float, float] | None = None,
        clock: Clock = now_iso_ms,
    ) -> None:
        self._unit = unit
        self._raw_read = raw_read
        self._calibrate = calibrate
        self._range = value_range
        self._clock = clock

    def _unhealthy(self, ts: str) -> Reading:
        return Reading(value=None, unit=self._unit, ts=ts, healthy=False)

    def read(self) -> Reading:
        ts = self._clock()
        try:
            raw = self._raw_read()
        except Exception:  # hardware/read failure — never propagates into the loop
            return self._unhealthy(ts)
        if raw is None:
            return self._unhealthy(ts)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return self._unhealthy(ts)
        if value != value:  # NaN
            return self._unhealthy(ts)
        if self._calibrate is not None:
            try:
                value = float(self._calibrate(value))
            except Exception:
                return self._unhealthy(ts)
            if value != value:  # NaN after calibration
                return self._unhealthy(ts)
        if self._range is not None:
            value = _clamp(value, self._range[0], self._range[1])
        return Reading(value=value, unit=self._unit, ts=ts, healthy=True)
