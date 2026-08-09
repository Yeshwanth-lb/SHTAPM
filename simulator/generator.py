"""Deterministic hardware-free telemetry generator (D005).

DEV / REPLAY SOURCE ONLY. This is **not** the Raspberry Pi edge acquisition
(that is P1, under ``edge/``). It exists so the backend/frontend telemetry path
can be built and demoed without the physical rig, and it doubles as the live
demo fallback (PRD R1/R2).

It emits the frozen M2 telemetry contract verbatim by constructing a
``TelemetryMessage`` (backend/app/schemas/contracts.py) — no field is renamed,
none is invented. No anomaly/trust/ML/decision logic lives here.

Determinism: values come from ``random.Random(seed)`` and depend only on
(seed, sample index), never on wall-clock. Timestamps are supplied by the
caller so tests are fully reproducible.

NOTE: the per-channel baseline means and ranges below are simulator-chosen
plausible bench values (datasheet-bounded), NOT authoritative spec numbers —
the docs specify sensor parts/analogues (PRD §12.1), not numeric baselines.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.schemas.contracts import CHANNELS, SensorReadings, TelemetryMessage

# (mean, noise_sd) — plausible steady-state bench baselines. Simulator-only.
BASELINES: dict[str, tuple[float, float]] = {
    "temperature": (26.0, 0.4),  # °C  — DS18B20 (motor/bearing temp)
    "vibration": (0.03, 0.005),  # g   — ADXL335 (bearing/cavitation)
    "pressure": (1013.0, 0.6),  # hPa — BMP180 (atmospheric proxy)
    "humidity": (45.0, 1.0),  # %   — DHT22 (seal-leak/wet-well)
    "gas": (150.0, 5.0),  # ppm — MQ-135 (VOC/CO2 proxy)
    "current": (0.42, 0.02),  # A   — INA219 (sub-1A pump load)
}

# Datasheet-bounded plausibility clamps (simulator-only).
RANGES: dict[str, tuple[float, float]] = {
    "temperature": (-55.0, 125.0),
    "vibration": (0.0, 3.0),
    "pressure": (300.0, 1100.0),
    "humidity": (0.0, 100.0),
    "gas": (0.0, 1000.0),
    "current": (0.0, 3.2),
}

# Decimal places per channel for stable, readable output.
_PRECISION: dict[str, int] = {
    "temperature": 2,
    "vibration": 4,
    "pressure": 2,
    "humidity": 2,
    "gas": 1,
    "current": 3,
}


@dataclass
class TelemetrySimulator:
    """Produces successive frozen ``TelemetryMessage`` samples deterministically."""

    device_id: str = "pump-01"
    seed: int = 1337
    _rng: random.Random = field(init=False, repr=False)
    _seq: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _sample_channel(self, channel: str) -> float:
        mean, sd = BASELINES[channel]
        lo, hi = RANGES[channel]
        value = self._rng.gauss(mean, sd)
        value = max(lo, min(hi, value))  # clamp to plausible range
        return round(value, _PRECISION[channel])

    def next(self, ts: str) -> TelemetryMessage:
        """Return the next telemetry sample stamped with the caller-supplied ts."""
        readings = {ch: self._sample_channel(ch) for ch in CHANNELS}
        message = TelemetryMessage(
            device_id=self.device_id,
            ts=ts,
            sensors=SensorReadings(**readings),
            sample_seq=self._seq,
        )
        self._seq += 1
        return message

    def generate(self, count: int, timestamps: list[str]) -> list[TelemetryMessage]:
        """Deterministically generate ``count`` samples using the given timestamps."""
        if len(timestamps) != count:
            raise ValueError("timestamps length must equal count")
        return [self.next(timestamps[i]) for i in range(count)]
