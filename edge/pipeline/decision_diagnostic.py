"""P2 diagnostic-decision reporting: WindowOutcome -> wire payload -> best-
effort MQTT publish, on ``shtapm/{device_id}/decision_diagnostic``.

NOT the frozen Doc05 §05.8 ``DecisionMessage`` / ``.../decision`` topic —
see ``backend/app/schemas/decision_diagnostic.py``'s own docstring for why
a separate schema/topic exists (the frozen one requires fields — health,
failure_eta, rl_action, substituted — that nothing in this project computes
live yet; fabricating them was rejected). This module only reports already-
computed P2 outputs; it computes nothing new and decides nothing.

BEST-EFFORT, FIRE-AND-FORGET (deliberately, not FR-Q4): no LWT, no buffered
resume, no retry, no delivery guarantee. ``DecisionDiagnosticPublisher`` is
a wholly separate object from ``edge.acquisition.mqtt_publisher.
ResilientTelemetryPublisher`` (its own client, its own connection) — a
broker rejecting this topic, or any exception anywhere in this module,
can structurally never affect telemetry publishing or P2 monitoring, which
neither import nor call into this module.

NOT EVIDENCE OF ACTUATION: ``isolation_candidates``/
``tracked_isolation_candidates`` come straight from the existing, unmodified
``edge/pipeline/isolation_fallback.py``/``isolation_tracker.py`` (stateless
classification / persistent tracking) — this module does not call
``process_isolated_channels``, ``SelfHealOrchestrator``, actuation, or
ledger/GPIO/relay code, and imports none of them.
"""

from __future__ import annotations

import logging

from app.schemas.contracts import CHANNELS, TrustScores
from app.schemas.decision_diagnostic import ChannelAttribution, DecisionDiagnosticMessage

from edge.anomaly.pipeline import WindowOutcome
from edge.pipeline.isolation_tracker import IsolationTrackerResult
from edge.pipeline.monitor import RawChannelValues

log = logging.getLogger("shtapm.edge.decision_diagnostic")

TOPIC = "shtapm/{device_id}/decision_diagnostic"


def build_decision_diagnostic_message(
    device_id: str,
    outcome: WindowOutcome,
    tracked: IsolationTrackerResult,
    raw: RawChannelValues,
) -> DecisionDiagnosticMessage:
    """Pure mapping, no I/O: the exact fields a ``WindowOutcome`` + the
    paired ``RawChannelValues`` + the current ``IsolationTrackerResult``
    already carry, reshaped into the wire payload. Invents no value —
    every field is read directly from an existing, already-computed
    object."""
    return DecisionDiagnosticMessage(
        device_id=device_id,
        ts=raw.ts,
        sample_seq=raw.sample_seq,
        window_start_index=outcome.window.start_index,
        window_end_index=outcome.window.end_index,
        anomaly_flag=outcome.anomaly.flag,
        anomaly_severity=outcome.anomaly.severity,
        trust=TrustScores(**{ch: outcome.trust[ch].trust for ch in CHANNELS}),
        attribution={
            ch: ChannelAttribution(
                attribution=outcome.attribution[ch].attribution,
                reason=outcome.attribution[ch].reason,
            )
            for ch in CHANNELS
        },
        isolation_candidates=sorted(tracked.candidates_this_cycle),
        tracked_isolation_candidates=sorted(tracked.tracked_channels),
    )


class DecisionDiagnosticPublisher:
    """Best-effort, fire-and-forget publisher for the diagnostic topic —
    see module docstring. No LWT, no buffering, no retry, no delivery
    guarantee. Every method swallows its own exceptions; none can ever
    raise into a caller."""

    def __init__(self, *, device_id: str) -> None:
        self.topic = TOPIC.format(device_id=device_id)
        self._client = None

    def start(self, host: str, port: int) -> None:
        """Best-effort connect. A failure here (missing paho, bad host,
        connect error) leaves this publisher permanently in its inert
        (no-op) state — it never retries and never raises."""
        try:
            import paho.mqtt.client as mqtt

            client = mqtt.Client()
            client.connect_async(host, port)
            client.loop_start()
            self._client = client
        except Exception:
            log.debug("decision diagnostic publisher failed to start (best-effort)", exc_info=False)
            self._client = None

    def stop(self) -> None:
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            log.debug("decision diagnostic publisher failed to stop cleanly (best-effort)")
        self._client = None

    def publish(self, message: DecisionDiagnosticMessage) -> None:
        """Fire-and-forget: a not-yet-started/failed-to-start publisher
        (``self._client is None``) silently drops the message; a live
        client's own publish failure is caught and dropped the same way.
        Never raises, never blocks, never buffers."""
        if self._client is None:
            return
        try:
            self._client.publish(self.topic, message.model_dump_json(), qos=0)
        except Exception:
            log.debug("decision diagnostic publish failed (best-effort, dropped)", exc_info=False)
