"""Shared telemetry-frame builder (C2).

ONE place that constructs the frozen ``TelemetryMessage`` so the simulator and
the edge sampler cannot drift into two builders. Preserves the frozen contract
EXACTLY — no field / validation / serialization change (``contracts.py`` is
untouched). No import cycle: this imports the contract; the contract imports
nothing from here.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.schemas.contracts import SensorReadings, TelemetryMessage


def build_telemetry(
    device_id: str,
    ts: str,
    sensors: Mapping[str, float],
    sample_seq: int,
) -> TelemetryMessage:
    """Build a frozen ``TelemetryMessage``.

    ``sensors`` must be exactly the six frozen channels — ``SensorReadings``
    enforces this (missing/extra keys → ``ValidationError``). Produces byte-for-
    byte the same message the simulator built inline previously.
    """
    return TelemetryMessage(
        device_id=device_id,
        ts=ts,
        sensors=SensorReadings(**sensors),
        sample_seq=sample_seq,
    )
