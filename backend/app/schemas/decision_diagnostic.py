"""Diagnostic-only P2 decision-reporting payload — NOT the frozen Doc05
§05.8 ``DecisionMessage`` (``app.schemas.contracts``), and NOT published on
the reserved ``shtapm/{device_id}/decision`` topic. This is a separate,
additive schema on ``shtapm/{device_id}/decision_diagnostic`` — see
``edge/pipeline/decision_diagnostic.py`` for the edge-side producer.

WHY A SEPARATE SCHEMA/TOPIC, NOT THE FROZEN ONE: ``DecisionMessage``
requires ``health``, ``failure_eta``, ``rl_action``, and ``substituted`` —
none of which anything in this project computes live yet (no prognosis,
no RL policy, no self-healing is wired into the live path). Filling those
with placeholder values to satisfy the frozen schema would mean publishing
fabricated health/action/substitution state — exactly what this project's
own discipline forbids. This schema instead carries only what a P2
``WindowOutcome`` (``edge/anomaly/pipeline.py``) and the existing, log-only
FR-RL4 isolation-candidate tracking (``edge/pipeline/isolation_fallback.py``,
``isolation_tracker.py``) genuinely compute today.

NOT EVIDENCE OF ACTUATION: ``isolation_candidates``/
``tracked_isolation_candidates`` are FR-RL4's existing stateless/persistent
CANDIDATE classifications — never a real isolation, substitution, or
self-heal action taken on any sensor. ``execution_mode``/``data_source``/
``model_status`` self-identify this payload as non-authoritative, the same
convention already used throughout ``edge/eval/u06_*.py``'s diagnostic
reports — no measured/validated claim is made anywhere in this schema.

``app.schemas.contracts`` (the frozen D006/D007 wire contract) is
UNTOUCHED — this module only imports already-existing, unmodified types
from it (``Channel``, ``Attribution``, ``Score``, ``TrustScores``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.contracts import Attribution, Channel, Score, TrustScores


class _Strict(BaseModel):
    """Reject unknown/renamed fields, same discipline as the frozen contract."""

    model_config = ConfigDict(extra="forbid")


class ChannelAttribution(_Strict):
    attribution: Attribution
    reason: str


class DecisionDiagnosticMessage(_Strict):
    device_id: str
    ts: str  # ISO-8601 with ms — the originating telemetry frame's own ts
    sample_seq: int  # the originating telemetry frame's own sample_seq
    window_start_index: int
    window_end_index: int
    anomaly_flag: bool
    anomaly_severity: Score
    trust: TrustScores  # per-channel, reused verbatim from the frozen contract
    # per-channel — no single-value reduction invented (see module docstring)
    attribution: dict[Channel, ChannelAttribution]
    isolation_candidates: list[Channel]  # FR-RL4 stateless, THIS cycle only — not real isolation
    tracked_isolation_candidates: list[Channel]  # FR-RL4 persistent — not real isolation
    execution_mode: Literal["live"] = "live"
    data_source: Literal["edge_live_pipeline"] = "edge_live_pipeline"
    model_status: Literal["diagnostic_unvalidated"] = "diagnostic_unvalidated"
