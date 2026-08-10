"""Hardware-free P2 pipeline orchestrator (internal — NOT a wire contract).

Wires the existing P2 components for one pass over a telemetry stream:

    frames -> Preprocessor -> Window
           -> AnomalyDetector          (window-level flag + severity, FR-A1)
           -> ChannelFlagPolicy        (window-level anomaly -> per-channel flags)
           -> TrustEngine              (per-channel Beta update from c/k/h)
           -> AttributionEngine        (per-channel none/fault/attack)

Every component is INJECTED, so this module contains no detection algorithm, no
c/k/h definition, no physics, no thresholds, and no dataset/attack logic — those
live behind the seams and are supplied by the caller (tests use stubs).

Note on the flag bridge: the detector reports a single window-level anomaly
result (FR-A1), while attribution is per channel. Deriving per-channel flags
from a window-level result is UNDECIDED (it needs the real multivariate
detector's per-channel contributions), so it is delegated to an injected
:class:`ChannelFlagPolicy` rather than invented here.

Returns internal :class:`WindowOutcome` objects only. No REST/WS/wire contract
is created; ``contracts.py`` is untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.attribution import AttributionEngine, AttributionResult
from edge.anomaly.detector import AnomalyDetector, AnomalyResult, detect
from edge.anomaly.preprocess import Preprocessor, Window
from edge.trust.engine import SignalProvider, TrustEngine, TrustReading


@runtime_checkable
class ChannelFlagPolicy(Protocol):
    """Injectable bridge: window-level anomaly result -> per-channel flags.

    Contract only. The real policy (derived from the multivariate detector's
    per-channel contributions) is out of scope; tests supply a deterministic
    stub."""

    def flags(self, window: Window, anomaly: AnomalyResult) -> Mapping[str, bool]: ...


@dataclass(frozen=True)
class WindowOutcome:
    """Everything the pipeline produced for one window (internal structure)."""

    window: Window
    anomaly: AnomalyResult
    channel_flags: dict[str, bool]
    trust: dict[str, TrustReading]
    attribution: dict[str, AttributionResult]


class P2Pipeline:
    """Orchestrates the injected P2 components over a telemetry stream."""

    def __init__(
        self,
        preprocessor: Preprocessor,
        detector: AnomalyDetector,
        trust_engine: TrustEngine,
        attribution_engine: AttributionEngine,
        c_provider: SignalProvider,
        k_provider: SignalProvider,
        h_provider: SignalProvider,
        flag_policy: ChannelFlagPolicy,
    ) -> None:
        self._pre = preprocessor
        self._detector = detector
        self._trust = trust_engine
        self._attribution = attribution_engine
        self._c = c_provider
        self._k = k_provider
        self._h = h_provider
        self._flag_policy = flag_policy

    def process(self, frames: list[TelemetryMessage]) -> list[WindowOutcome]:
        """Run the full pass. One :class:`WindowOutcome` per full window; an
        empty result if the stream is shorter than the window size.

        The trust engine is stateful: each window applies one Beta update per
        channel, so trust evolves across windows while channels stay
        independent."""
        outcomes: list[WindowOutcome] = []
        for window in self._pre.process(frames):
            anomaly = detect(self._detector, window)
            flags = dict(self._flag_policy.flags(window, anomaly))
            trust = self._trust.update_from_providers(self._c, self._k, self._h)
            attribution = self._attribution.attribute(flags, window)
            outcomes.append(
                WindowOutcome(
                    window=window,
                    anomaly=anomaly,
                    channel_flags=flags,
                    trust=trust,
                    attribution=attribution,
                )
            )
        return outcomes

    @staticmethod
    def channels() -> tuple[str, ...]:
        """The frozen channel set the pipeline operates over."""
        return CHANNELS
