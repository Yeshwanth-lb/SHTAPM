"""Live self-healing wiring: trained twin -> substitution for isolated channels.

Composes the already-built, previously-dormant P3 pieces
(``SelfHealOrchestrator``, ``process_isolated_channels``, ``DivergenceScorer``,
``ElapsedTimeUncertaintyProxy``, ``LSTMTwinReconstructor``) into something
``edge/main.py`` can call once per cycle. It adds no new self-healing logic of
its own -- every behavioural rule still lives in the modules above.

WHAT THIS DOES: when P2 marks a channel as an isolation candidate, reconstruct
that channel from the others and report a substituted value in ENGINEERING
UNITS (D029's fixed scale makes the reconstruction invertible).

WHAT THIS DELIBERATELY DOES NOT DO:

  * **No actuation.** ``safe_stop`` is a log-only callback. No relay, no GPIO,
    no pump control is wired, by explicit project instruction.
  * **No divergence escalation.** ``divergence_threshold`` is +inf, so the
    escalate-to-Safe-Pump-Stop path can never fire. This is not a placeholder
    awaiting a number: U05 is open *because the measurement failed*. On clean
    held-out bench data the false-escalation rate was 5.8% at 3 sigma and still
    4.2% at 6 sigma, with a maximum clean divergence of 68.4 sigma -- roughly
    one spurious stop every 24 windows at 1 Hz (see
    ``project-state/BENCH_LOAD_VALIDATION.md`` §8). Divergence is still
    COMPUTED and reported every cycle; only the escalation is disabled.
  * **No telemetry substitution.** The reconstructed value is reported
    alongside the frame, never written into it. The frozen contract's
    ``sensors`` block keeps carrying what the sensor actually said, so nothing
    downstream can mistake a reconstruction for a measurement.

DEGRADES GRACEFULLY: with no twin bundle present this returns nothing and logs
once. A missing model must never stop telemetry -- the same fail-safe posture
FR-RL4 requires of a missing RL policy.

SCALE: the twin consumes windows in D029's fixed clean-baseline scale, NOT the
per-window min-max windows P2 produces. Those are different spaces and are not
interchangeable, so this module builds its own window from the raw frames.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.pipeline import WindowOutcome
from edge.anomaly.preprocess import Window
from edge.models.twin_bundle import TwinBundle, load_bundle
from edge.pipeline.cycle import process_isolated_channels
from edge.pipeline.divergence import DivergenceScorer
from edge.pipeline.self_heal import UNCERTAINTY_CAP_D020, SelfHealOrchestrator, SelfHealOutcome
from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy, linear_scaling

log = logging.getLogger("shtapm.edge.self_heal_runtime")

# U05 is open because the measurement FAILED, not because it is pending -- see
# module docstring. +inf makes the escalation path unreachable by construction
# rather than by a conveniently large guess.
ESCALATION_DISABLED_THRESHOLD = math.inf


@dataclass(frozen=True)
class SubstitutionReport:
    """One channel's substitution result for one cycle, in engineering units.

    ``substituted_value`` is what the twin reconstructed, converted back through
    D029's fixed scale. ``observed_value`` is what the sensor actually reported
    for the same cycle. Both are carried so a consumer can show the disagreement
    rather than only the replacement.
    """

    channel: str
    substituted_value: float
    observed_value: float
    divergence: float | None
    uncertainty: float | None
    unit_space: str = "engineering"


def _log_only_safe_stop() -> None:
    """Stands in for Safe Pump-Stop. Actuation is not wired, by instruction.

    Unreachable while ``divergence_threshold`` is +inf and the substitution
    window is unbounded, but supplied explicitly: SelfHealOrchestrator requires
    a callable, and a silent lambda would hide that a real one is absent.
    """
    log.warning(
        "safe-stop requested by self-heal orchestrator -- NOT actuated "
        "(no actuation is wired in this build)"
    )


class SelfHealRuntime:
    """Per-cycle substitution for isolated channels, driven by a trained twin."""

    def __init__(self, bundle: TwinBundle, window_size: int) -> None:
        self._bundle = bundle
        self._window_size = window_size

        scorer = DivergenceScorer()
        scorer.fit(bundle.divergence_fit())
        self._orchestrator = SelfHealOrchestrator(
            twin=bundle.reconstructor,
            divergence_scorer=scorer,
            uncertainty_proxy=ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling),
            divergence_threshold=ESCALATION_DISABLED_THRESHOLD,
            uncertainty_cap=UNCERTAINTY_CAP_D020,
            safe_stop=_log_only_safe_stop,
            # The substitution clock is left at its D018 default; with
            # escalation disabled, expiry cannot actuate either.
        )

    @property
    def channel(self) -> str:
        """The single channel this runtime can substitute.

        One bundle reconstructs one channel. On this bench that is `current`:
        it is the only channel measured to be reconstructable (45.8% skill
        against a predict-the-mean baseline; `vibration` reached 5.6% and was
        not deployed).
        """
        return self._bundle.channel

    def _scaled_window(self, frames: Sequence[TelemetryMessage]) -> Window | None:
        """Build a window in the twin's own fixed scale from raw frames.

        Returns None unless exactly ``window_size`` frames are available and
        every channel the bundle was fitted on is present -- a short or
        partially-scaled window would be silently wrong rather than obviously
        broken.
        """
        if len(frames) < self._window_size:
            return None
        recent = list(frames)[-self._window_size :]
        fitted = self._bundle.scaler.fitted_channels
        features: dict[str, tuple[float, ...]] = {}
        for channel in CHANNELS:
            if channel in fitted:
                features[channel] = tuple(
                    self._bundle.scaler.normalize(channel, getattr(f.sensors, channel))
                    for f in recent
                )
            else:
                # Not fitted (e.g. `gas`, which no driver measures): 0.0 is the
                # channel mean in z-score space, i.e. "no information" -- the
                # same representation training used.
                features[channel] = (0.0,) * self._window_size
        return Window(start_index=0, end_index=self._window_size, features=features)

    def substitute(
        self,
        outcome: WindowOutcome,
        isolated_channels: frozenset[str],
        frames: Sequence[TelemetryMessage],
    ) -> list[SubstitutionReport]:
        """Reconstruct any isolated channel this runtime can serve.

        Returns an empty list when nothing is isolated, when the isolated set
        does not include this bundle's channel, or when no usable window is
        available yet. Never raises into the caller: a self-healing fault must
        not stop telemetry.
        """
        target = self._bundle.channel
        if target not in isolated_channels:
            return []

        window = self._scaled_window(frames)
        if window is None:
            return []

        try:
            results = process_isolated_channels(
                outcome,
                isolated_channels=frozenset({target}),
                raw_values={target: getattr(frames[-1].sensors, target)},
                orchestrator=self._orchestrator,
                window_override=window,
            )
        except Exception:
            log.exception("self-heal substitution failed for %s", target)
            return []

        return [
            report
            for channel, result in results.items()
            if (report := self._to_report(channel, result)) is not None
        ]

    def _to_report(self, channel: str, result: SelfHealOutcome) -> SubstitutionReport | None:
        if not result.substituted or result.reconstructed_value is None:
            return None
        scaler = self._bundle.scaler
        return SubstitutionReport(
            channel=channel,
            substituted_value=scaler.denormalize(channel, result.reconstructed_value),
            observed_value=(
                scaler.denormalize(channel, result.observed_value)
                if result.observed_value is not None
                else float("nan")
            ),
            divergence=result.divergence,
            uncertainty=result.uncertainty,
        )


def load_self_heal_runtime(model_dir: str | Path, window_size: int) -> SelfHealRuntime | None:
    """Load the twin bundle from ``model_dir`` if one is present.

    Returns None -- having logged why -- when no bundle exists or it cannot be
    loaded. Substitution is then simply unavailable; telemetry, P2 and
    isolation reporting all continue unchanged.
    """
    directory = Path(model_dir)
    bundles = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not bundles:
        log.info(
            "no twin bundle in %s -- self-healing substitution is UNAVAILABLE "
            "(train one with edge/eval/bench_twin_training.py --save-prefix)",
            directory,
        )
        return None

    path = bundles[0].with_suffix("")
    try:
        bundle = load_bundle(path)
    except Exception:
        log.exception("twin bundle at %s could not be loaded; substitution UNAVAILABLE", path)
        return None

    log.info(
        "twin bundle loaded: channel=%s skill=%.1f%% trained_on=%s "
        "(divergence escalation DISABLED -- U05 unresolved)",
        bundle.channel,
        bundle.skill * 100.0,
        bundle.trained_on,
    )
    return SelfHealRuntime(bundle, window_size=window_size)
