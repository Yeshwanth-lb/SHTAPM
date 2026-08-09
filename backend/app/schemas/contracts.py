"""SHTAPM canonical shared data contract (D006 / D007) — P0 stub.

Authoritative field names and shapes come from **Doc05 §05.8** (see
project-state/DECISIONS.md D007). PRD §10.3 shorthand (``temp``/``vib``,
``s1..s6``, nested ``healing:{}``) is explicitly superseded.

Scope: schema / validation stub ONLY. No MQTT, no simulator, no ML, no business
logic. This module is the single Python source of truth for the wire contract;
``frontend/src/types/contracts.ts`` mirrors it verbatim, and future
edge/simulator/backend code consume these models.

Envelope (ruling E): MQTT canonical payloads carry NO ``type`` field — the MQTT
topic (telemetry/decision/ledger/status/command) identifies the category. The
WebSocket layer wraps a payload as ``{"type": <category>, **payload}``. The
payload fields are otherwise identical on MQTT and WebSocket.

Not frozen here (out of M2 scope): ``device_status`` / ``system_health`` /
``alert`` WS frames (Doc05 §05.8) — frozen in P4; and the ``command`` payload,
which is UNSPECIFIED in the docs (U14) and must not be invented.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Frozen six-channel order (ruling A/B). Names match Doc05 sensors.channel ENUM,
# sensor_readings columns, and the WS telemetry/decision frames.
CHANNELS: tuple[str, ...] = (
    "temperature",
    "vibration",
    "pressure",
    "humidity",
    "gas",
    "current",
)


class Channel(str, Enum):
    temperature = "temperature"
    vibration = "vibration"
    pressure = "pressure"
    humidity = "humidity"
    gas = "gas"
    current = "current"


class Attribution(str, Enum):  # Doc05 decisions.attribution
    none = "none"
    fault = "fault"
    attack = "attack"


class HealthState(str, Enum):  # Doc05 decisions.health_state (wire field: "health")
    healthy = "healthy"
    warning = "warning"
    critical = "critical"


class RLAction(str, Enum):  # Doc05 decisions.rl_action
    continue_ = "continue"  # "continue" is a Python keyword; value stays canonical
    reduce_weight = "reduce_weight"
    isolate = "isolate"
    alert = "alert"
    safe_stop = "safe_stop"


# Trust and severity are scores in [0, 1] (FR-T1; Doc05 "0–1").
Score = Annotated[float, Field(ge=0.0, le=1.0)]


class _Strict(BaseModel):
    """Reject unknown/renamed fields so the frozen contract can't silently drift."""

    model_config = ConfigDict(extra="forbid")


class SensorReadings(_Strict):
    temperature: float
    vibration: float
    pressure: float
    humidity: float
    gas: float
    current: float


class TelemetryMessage(_Strict):
    device_id: str
    ts: str  # ISO-8601 with ms (FR-Q2); kept as string on the wire
    sensors: SensorReadings
    sample_seq: int


class AnomalyInfo(_Strict):
    flag: bool
    severity: Score
    attribution: Attribution
    reason: str


class TrustScores(_Strict):
    temperature: Score
    vibration: Score
    pressure: Score
    humidity: Score
    gas: Score
    current: Score


class DecisionMessage(_Strict):
    device_id: str
    ts: str
    anomaly: AnomalyInfo
    trust: TrustScores
    health: HealthState
    failure_eta: float  # cycles/seconds ahead (Doc05); short-horizon (FR-M2)
    rl_action: RLAction
    isolated: list[Channel]  # ruling C — flat arrays, not nested healing:{}
    substituted: list[Channel]


class LedgerMessage(_Strict):
    device_id: str
    ts: str
    block_index: int
    event: str  # stored as ledger_blocks.event_type; wire field name is "event"
    payload_hash: str  # ruling D — kept (required by hash-chain verification)
    prev_hash: str
    this_hash: str


class WSFrameType(str, Enum):
    telemetry = "telemetry"
    decision = "decision"
    ledger = "ledger"
    device_status = "device_status"
    system_health = "system_health"
    alert = "alert"
