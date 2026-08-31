"""P2-to-P3 narrow adapter: wire an existing P2 ``WindowOutcome`` into the
existing ``SelfHealOrchestrator`` for one processing cycle.

Scope (see project-state/DECISIONS.md D016-D019 and the P2->P3 cycle-wiring
scoping pass that preceded this module): P2 has no isolation-state output
anywhere in this repo -- no object, field, or method marks a channel as
"isolated." FR-RL2 makes isolation an RL-agent action ("Isolate Sensor"),
and both the RL agent and its deterministic fallback (FR-RL4) are unbuilt.
Inferring isolation from trust or ``TrustBand`` here would invent that
missing decision layer's rule, which this module deliberately does NOT do.

``isolated_channels`` and ``raw_values`` are therefore REQUIRED, caller-
supplied inputs with no default -- the same "required parameter, no
invented value" discipline already used for ``divergence_threshold``/
``uncertainty_cap``/the uncertainty scaling formula. This module contains
no isolation policy, no RL/fallback logic, and no numeric/specification
value.

``raw_values`` cannot be sourced from ``WindowOutcome``: ``Preprocessor``
discards the true raw reading before building ``Window`` (filtered +
per-window min-max normalized only), so the caller must supply it
separately from the original telemetry stream (D018's Interpretation A:
"the isolated channel's continuing raw reading").

This module only reads ``WindowOutcome``/``SelfHealOrchestrator`` and calls
``SelfHealOrchestrator.process_isolated_channel`` -- it does not modify
``edge/anomaly/pipeline.py``, ``edge/trust/*``, ``contracts.py``,
``simulator/``, ``edge/actuation/*``, or ``edge/pipeline/self_heal.py``.
Preserves the existing monitoring-only invariant: the raw value flows in
exactly once per call and is never returned or fed back into P2.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from app.schemas.contracts import CHANNELS

from edge.anomaly.pipeline import WindowOutcome
from edge.pipeline.self_heal import SelfHealOrchestrator, SelfHealOutcome


def process_isolated_channels(
    outcome: WindowOutcome,
    isolated_channels: Collection[str],
    raw_values: Mapping[str, float],
    orchestrator: SelfHealOrchestrator,
) -> dict[str, SelfHealOutcome]:
    """Run ``orchestrator.process_isolated_channel`` for exactly the
    channels named in ``isolated_channels`` -- no more, no fewer.

    Args:
        outcome: this cycle's P2 ``WindowOutcome`` (read-only; supplies
            ``outcome.window`` and ``outcome.trust[channel].trust``).
        isolated_channels: the channels the caller has already determined
            are isolated. REQUIRED -- never derived from ``outcome.trust``
            or ``TrustBand`` by this function.
        raw_values: channel -> continuing raw reading for this cycle.
            REQUIRED -- not obtainable from ``outcome`` (see module
            docstring).
        orchestrator: the already-configured ``SelfHealOrchestrator``.

    Returns:
        ``{channel: SelfHealOutcome}`` for exactly the channels in
        ``isolated_channels``. Empty if ``isolated_channels`` is empty.

    Raises:
        ValueError: a channel in ``isolated_channels`` is not present in
            ``outcome.trust`` (i.e. not one of the frozen ``CHANNELS``), or
            ``raw_values`` is missing an entry for a channel in
            ``isolated_channels``.
    """
    results: dict[str, SelfHealOutcome] = {}
    for channel in isolated_channels:
        if channel not in outcome.trust:
            raise ValueError(
                f"isolated_channels names {channel!r}, which is not present in "
                f"outcome.trust (must be one of {CHANNELS})"
            )
        if channel not in raw_values:
            raise ValueError(
                f"raw_values is missing a required entry for isolated channel {channel!r}"
            )
        results[channel] = orchestrator.process_isolated_channel(
            channel=channel,
            window=outcome.window,
            raw_value=raw_values[channel],
            trust=outcome.trust[channel].trust,
        )
    return results
