"""Per-channel trust engine shell (P2 · U01 foundation).

Wraps the signal-agnostic :mod:`edge.trust.beta` core with one
:class:`~edge.trust.beta.BetaState` per telemetry channel. It consumes
per-channel evidence signals ``(c, k, h)`` — supplied by the caller — combines
them into ``g`` with the documented weights, updates that channel's Beta state,
and returns the trust score + band.

This module is deliberately signal-agnostic: it does NOT define, compute, or
assume what consistency ``c``, cross-sensor correlation ``k``, or historical
reliability ``h`` actually mean. Those definitions are UNDECIDED (U01/U02) and
must be supplied through the :class:`SignalProvider` seam (real implementations
land later). No Isolation Forest, physics rule, dataset logic, or attribution
lives here.

Forgetting factor: reuses ``beta.DEFAULT_LAMBDA`` (0.7), which remains a
**pending-approval U01 value** (see :mod:`edge.trust.beta`). It is not a
documented specification number.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.schemas.contracts import CHANNELS

from edge.trust.beta import (
    DEFAULT_LAMBDA,
    BetaState,
    TrustBand,
    combine_g,
)


@runtime_checkable
class SignalProvider(Protocol):
    """Seam for a single trust signal (used once each for c, k, h).

    ``evaluate(channel)`` returns that signal's score in [0, 1] for the given
    channel. Contract only — it says nothing about how the score is derived.
    Real providers (IF residual for c, physics for k, reliability memory for h)
    are implemented later, gated on U01/U02."""

    def evaluate(self, channel: str) -> float: ...


@dataclass(frozen=True)
class TrustReading:
    """Result of one channel update: the evidence and the resulting trust."""

    channel: str
    g: float
    trust: float
    band: TrustBand


class TrustEngine:
    """Holds one Beta-reputation state per channel and updates them from
    supplied ``(c, k, h)`` signals."""

    def __init__(self, *, forgetting: float = DEFAULT_LAMBDA) -> None:
        # One independent BetaState per frozen channel (priors alpha0=beta0=1).
        self._states: dict[str, BetaState] = {
            ch: BetaState(forgetting=forgetting) for ch in CHANNELS
        }

    def _require_channel(self, channel: str) -> BetaState:
        state = self._states.get(channel)
        if state is None:
            raise ValueError(f"unknown channel {channel!r}; must be one of {CHANNELS}")
        return state

    def update_channel(self, channel: str, c: float, k: float, h: float) -> TrustReading:
        """Combine ``(c, k, h)`` into ``g`` (documented 0.4/0.3/0.3 weights),
        apply one Beta window to ``channel``, and return the new reading.

        ``combine_g`` validates each signal is in [0, 1]; ``BetaState.update``
        validates ``g``."""
        state = self._require_channel(channel)
        g = combine_g(c, k, h)
        trust = state.update(g)
        return TrustReading(channel=channel, g=g, trust=trust, band=state.band)

    def update_all(
        self, signals: Mapping[str, tuple[float, float, float]]
    ) -> dict[str, TrustReading]:
        """Update every channel present in ``signals`` (a subset is allowed).
        Each value is a ``(c, k, h)`` triple."""
        return {channel: self.update_channel(channel, *ckh) for channel, ckh in signals.items()}

    def update_from_providers(
        self,
        c_provider: SignalProvider,
        k_provider: SignalProvider,
        h_provider: SignalProvider,
        channels: tuple[str, ...] = CHANNELS,
    ) -> dict[str, TrustReading]:
        """Pull ``(c, k, h)`` per channel from three providers, then update."""
        out: dict[str, TrustReading] = {}
        for ch in channels:
            self._require_channel(ch)
            out[ch] = self.update_channel(
                ch,
                c_provider.evaluate(ch),
                k_provider.evaluate(ch),
                h_provider.evaluate(ch),
            )
        return out

    def trust(self, channel: str) -> float:
        """Current trust score for ``channel``."""
        return self._require_channel(channel).trust

    def band(self, channel: str) -> TrustBand:
        """Current trust band for ``channel``."""
        return self._require_channel(channel).band

    def snapshot(self) -> dict[str, TrustReading]:
        """Current reading for every channel without applying any update
        (``g`` is reported as 0.0 — no evidence was consumed)."""
        return {
            ch: TrustReading(channel=ch, g=0.0, trust=st.trust, band=st.band)
            for ch, st in self._states.items()
        }
