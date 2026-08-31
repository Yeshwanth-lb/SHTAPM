"""Self-heal orchestrator: isolation -> substitution -> divergence backstop
-> Safe Pump-Stop (P3 · FR-H1-H4, D016-D019).

Wires the injected TwinReconstructor, DivergenceScorer, and UncertaintyProxy
seams together with D018's behavioral rules (recovery at TRUSTED_MIN,
60-second substitution expiry, cycle sequencing) and D019's uncertainty
method. Every numeric specification value this project has NOT decided
(divergence_threshold, uncertainty_cap, and -- via the injected
UncertaintyProxy -- the scaling formula) is a REQUIRED constructor argument
with no default: this module cannot silently invent U05.

Three signals stay independent, per explicit instruction:
  - uncertainty proxy output   vs uncertainty_cap
  - elapsed substitution time  vs substitution_max_seconds
  - z-score divergence         vs divergence_threshold
All three are always computed and reported in SelfHealOutcome; none of the
three comparisons is derived from, or gates the computation of, another.

Called once per isolated channel per cycle, AFTER P2 (trust/isolation
determination) has already run (D018 pt.5). Does not import or modify
edge/anomaly/pipeline.py or any P2 component -- it only consumes
(channel, window, raw_value, trust) as plain arguments.

safe_stop is injected as a bare Callable[[], None] (the same decoupling
edge/actuation/watchdog.py already uses for on_expire) -- this module has no
import of edge.actuation. The caller wires e.g.
RelayController(actuator).safe_off in.

Returns internal dataclasses only (SelfHealOutcome / SelfHealAlert). No
DecisionMessage field, WS/wire frame, or `alerts` DB row is constructed
here -- Doc05's alerts table has no existing Python/wire schema anywhere in
this repo (WSFrameType.alert is a frame-type tag only; its payload is
explicitly out of scope in contracts.py), so persisting a real alerts row is
deferred to later backend wiring, consistent with D018 pt.4 ("uncertainty
stays edge-internal").
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Window
from edge.models.twin import TwinReconstructor
from edge.pipeline.divergence import DivergenceScorer
from edge.pipeline.uncertainty import UncertaintyProxy
from edge.trust.beta import TRUSTED_MIN

# Doc05 thresholds.substitution_max_seconds default (D018 pt.3: "already 60,
# Doc05 default") -- reused here as a single named, overridable default,
# mirroring edge/anomaly/preprocess.py's window_size=30 and
# edge/trust/beta.py's DEFAULT_LAMBDA precedent. Not a new/duplicated value.
SUBSTITUTION_MAX_SECONDS_DEFAULT: float = 60.0

# DECISIONS.md D020 (2026-08-31): approved uncertainty_cap value, in the
# uncertainty proxy's own output domain. NOT a default -- SelfHealOrchestrator
# still requires uncertainty_cap to be explicitly supplied by the caller.
# Exists only as a canonical, importable reference to avoid duplicated
# fixture copies drifting from the real approved value.
UNCERTAINTY_CAP_D020: float = 0.8


class EscalationReason:
    DIVERGENCE_EXCEEDED = "divergence_exceeded"
    SUBSTITUTION_EXPIRED = "substitution_expired"


@dataclass(frozen=True)
class SelfHealAlert:
    """Internal uncertainty-cap alert signal (P3-HEAL-E1 wording, D019). NOT
    the Doc05 `alerts` table row and NOT a wire frame -- see module
    docstring."""

    channel: str
    message: str
    reason: str


@dataclass(frozen=True)
class SelfHealOutcome:
    """Everything the orchestrator produced for one isolated channel in one
    cycle (internal structure, not a wire contract)."""

    channel: str
    substituted: bool
    reconstructed_value: float | None
    divergence: float | None
    uncertainty: float | None
    escalated: bool
    escalation_reason: str | None
    alert: SelfHealAlert | None


@dataclass
class _Episode:
    start_time: float


class SelfHealOrchestrator:
    """Isolation -> substitution -> divergence backstop -> Safe Pump-Stop."""

    def __init__(
        self,
        twin: TwinReconstructor,
        divergence_scorer: DivergenceScorer,
        uncertainty_proxy: UncertaintyProxy,
        divergence_threshold: float,
        uncertainty_cap: float,
        safe_stop: Callable[[], None],
        substitution_max_seconds: float = SUBSTITUTION_MAX_SECONDS_DEFAULT,
        trusted_min: float = TRUSTED_MIN,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if substitution_max_seconds <= 0:
            raise ValueError(
                f"substitution_max_seconds must be > 0, got {substitution_max_seconds}"
            )
        self._twin = twin
        self._divergence_scorer = divergence_scorer
        self._uncertainty_proxy = uncertainty_proxy
        self._divergence_threshold = divergence_threshold
        self._uncertainty_cap = uncertainty_cap
        self._safe_stop = safe_stop
        self._substitution_max_seconds = substitution_max_seconds
        self._trusted_min = trusted_min
        self._clock = clock
        self._episodes: dict[str, _Episode] = {}

    def process_isolated_channel(
        self, channel: str, window: Window, raw_value: float, trust: float
    ) -> SelfHealOutcome:
        """Run one cycle's substitution/divergence check for ``channel``,
        which P2 has already isolated this cycle (D018 pt.5 sequencing).

        Recovery: if ``trust >= trusted_min``, any active episode ends and no
        substitution is reported for this cycle (D018 pt.2). Otherwise the
        channel is (re)substituted: an episode starts if none is active for
        this channel, or continues if one already is. A new episode after a
        recovery starts elapsed time at zero (D019's reset semantics), since
        the episode dict entry was removed on recovery.
        """
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}; must be one of {CHANNELS}")

        if trust >= self._trusted_min:
            self._episodes.pop(channel, None)
            return SelfHealOutcome(
                channel=channel,
                substituted=False,
                reconstructed_value=None,
                divergence=None,
                uncertainty=None,
                escalated=False,
                escalation_reason=None,
                alert=None,
            )

        episode = self._episodes.get(channel)
        if episode is None:
            episode = _Episode(start_time=self._clock())
            self._episodes[channel] = episode

        reconstructed = self._twin.reconstruct(window, channel)
        residual = reconstructed - raw_value
        divergence = self._divergence_scorer.score(channel, residual)

        elapsed = self._clock() - episode.start_time
        uncertainty = self._uncertainty_proxy.uncertainty(elapsed, self._substitution_max_seconds)

        # Three independent signals: all three are always computed above,
        # regardless of which (if any) comparison below fires.
        alert = None
        if uncertainty >= self._uncertainty_cap:
            alert = SelfHealAlert(
                channel=channel,
                message="Uncertainty flagged high (nearing cap); alert raised",
                reason="uncertainty_near_cap",
            )

        if divergence >= self._divergence_threshold:
            self._episodes.pop(channel, None)
            self._safe_stop()
            return SelfHealOutcome(
                channel=channel,
                substituted=False,
                reconstructed_value=reconstructed,
                divergence=divergence,
                uncertainty=uncertainty,
                escalated=True,
                escalation_reason=EscalationReason.DIVERGENCE_EXCEEDED,
                alert=alert,
            )

        if elapsed >= self._substitution_max_seconds:
            self._episodes.pop(channel, None)
            self._safe_stop()
            return SelfHealOutcome(
                channel=channel,
                substituted=False,
                reconstructed_value=reconstructed,
                divergence=divergence,
                uncertainty=uncertainty,
                escalated=True,
                escalation_reason=EscalationReason.SUBSTITUTION_EXPIRED,
                alert=alert,
            )

        return SelfHealOutcome(
            channel=channel,
            substituted=True,
            reconstructed_value=reconstructed,
            divergence=divergence,
            uncertainty=uncertainty,
            escalated=False,
            escalation_reason=None,
            alert=alert,
        )
