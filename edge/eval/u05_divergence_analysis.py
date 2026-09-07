"""Offline residual/divergence analysis over a loaded bench capture (U05
evidence preparation) -- descriptive statistics only, NEVER a threshold.

Composes three already-existing, UNMODIFIED pieces over capture-shaped
data: ``edge.eval.u05_capture_loader`` (this module's own upstream),
``edge.models.twin.TwinReconstructor`` (the injected reconstruction seam
-- no architecture is chosen here; the caller supplies a real or fixture
implementation), and ``edge.pipeline.divergence.DivergenceScorer`` (the
already-approved fit-time z-score form, D018 pt.1). This module invents
NO reconstruction algorithm, NO divergence formula, and NO numeric
threshold -- it only wires already-approved pieces together over real
captured data and reports what came out, per
``project-state/DECISIONS.md``'s U05/U06 "no invented value" discipline.

WHAT THIS MODULE DOES NOT DO: choose or recommend a ``divergence_threshold``
value; label any window/capture as "fault" or "nominal" (that labeling is
the caller's own responsibility, from what they know about the capture --
this module never inspects filenames, timestamps, or metadata to guess);
claim any reconstruction is accurate merely because it ran; or feed
anything into ``SelfHealOrchestrator``/``process_isolated_channels`` (not
imported here, not called here). Running this with the UNTRAINED
``LSTMTwinReconstructor`` (no training on real data has occurred anywhere
in this repo) proves the analysis PIPELINE works end-to-end on real
telemetry -- it does not, and cannot, establish meaningful reconstruction
accuracy. See ``edge/eval/twin_training.py``'s own docstring for why: the
same "diagnostic plumbing, not accuracy" caveat applies here identically,
now extended from simulator data to real captured data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.preprocess import Window
from edge.eval.u05_capture_loader import raw_channel_values_for_window
from edge.models.twin import TwinReconstructor
from edge.pipeline.divergence import DivergenceScorer

EXECUTION_MODE = "offline_analysis"
MODEL_STATUS = "diagnostic_unvalidated"


def compute_residuals(
    windows: Sequence[Window],
    messages: Sequence[TelemetryMessage],
    twin: TwinReconstructor,
    *,
    channels: Sequence[str] = CHANNELS,
) -> dict[str, list[float]]:
    """``residual = twin.reconstruct(window, channel) - raw_value`` for
    every window and every requested channel, in window order. Pure
    infrastructure: invents no threshold, no fault label -- just the
    residual sequence a human (or ``DivergenceScorer.fit()``/``score()``)
    can analyze next. ``messages`` must be the same ordered list the
    windows were built from (see ``u05_capture_loader.windows_from_capture``)."""
    residuals: dict[str, list[float]] = {ch: [] for ch in channels}
    for window in windows:
        raw = raw_channel_values_for_window(window, messages)
        for ch in channels:
            reconstructed = twin.reconstruct(window, ch)
            residuals[ch].append(reconstructed - raw[ch])
    return residuals


@dataclass(frozen=True)
class ChannelDivergenceSummary:
    """Descriptive statistics ONLY for one channel's fitted z-scores over
    one capture -- no threshold, no verdict, no fault/nominal label.
    ``sample_count == 0`` (e.g. an unfitted channel, or a channel absent
    from ``channels``) reports every stat as ``None``, never a fabricated
    ``0.0``."""

    channel: str
    sample_count: int
    z_score_mean: float | None
    z_score_min: float | None
    z_score_max: float | None
    execution_mode: str = EXECUTION_MODE
    model_status: str = MODEL_STATUS


def score_residuals(
    residuals_by_channel: Mapping[str, Sequence[float]],
    scorer: DivergenceScorer,
) -> dict[str, ChannelDivergenceSummary]:
    """Score already-computed residuals against an already-fitted
    ``DivergenceScorer`` (see ``DivergenceScorer.fit()`` -- fit it on a
    capture segment you consider clean/nominal before calling this on any
    segment). Reports mean/min/max z-score per channel -- descriptive only.
    Choosing what these numbers mean for a ``divergence_threshold`` remains
    a separate, explicit human decision (U05, data-gated)."""
    summaries: dict[str, ChannelDivergenceSummary] = {}
    for channel, values in residuals_by_channel.items():
        if not values:
            summaries[channel] = ChannelDivergenceSummary(channel, 0, None, None, None)
            continue
        scores = [scorer.score(channel, value) for value in values]
        summaries[channel] = ChannelDivergenceSummary(
            channel=channel,
            sample_count=len(scores),
            z_score_mean=sum(scores) / len(scores),
            z_score_min=min(scores),
            z_score_max=max(scores),
        )
    return summaries
