"""Attribution-engine shell: fault-vs-attack plumbing (P2 · FR-A2/FR-A3).

Implements ONLY the documented attribution *structure*, per channel:

    no anomaly flag                         -> none
    anomaly + physics consistent            -> fault
    anomaly + physics violation (suspect)   -> attack

The physics itself is NOT here. Whether a cross-sensor physics violation
occurred, which channel is the suspect, and the human ``reason`` all come from
an injected :class:`PhysicsRule`. This module invents NO current<->pressure
equation, tolerance, or any other physics — the documented reason string
("physics violation: pressure vs current") is used only as a passthrough
template supplied by the rule.

Attribution is per channel so a simultaneous fault on one channel and attack on
another are represented independently (PRD P2-ANOM-E2).

Uses the frozen contract's :class:`~app.schemas.contracts.Attribution` enum
internally; the contract is not modified. No Isolation Forest, no c/k/h, no
dataset, no attack magnitudes, no hardware logic here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.preprocess import Window

# Reason templates (NOT physics claims). The attack reason is normally supplied
# by the PhysicsRule; this is only the fallback wording.
REASON_NONE = ""
REASON_FAULT = "anomaly: physics consistent"
REASON_ATTACK_FALLBACK = "physics violation"


@dataclass(frozen=True)
class PhysicsCheck:
    """Result of a cross-sensor physics check for one window.

    ``violated`` — whether a physics inconsistency was detected.
    ``suspect_channel`` — the channel deemed to be lying (or ``None`` if the
    violation cannot be attributed to a specific channel).
    ``reason`` — human-readable explanation (rule-supplied template)."""

    violated: bool
    suspect_channel: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.suspect_channel is not None and self.suspect_channel not in CHANNELS:
            raise ValueError(
                f"suspect_channel must be a known channel or None, got {self.suspect_channel!r}"
            )


@runtime_checkable
class PhysicsRule(Protocol):
    """Injectable cross-sensor physics check. Contract only — it says nothing
    about the actual relationship, direction, or tolerance (UNDECIDED, U02;
    data-gated). Real rules are implemented later."""

    def check(self, window: Window) -> PhysicsCheck: ...


@dataclass(frozen=True)
class AttributionResult:
    """Per-channel attribution outcome."""

    channel: str
    attribution: Attribution
    reason: str


class AttributionEngine:
    """Applies the documented attribution branch logic using an injected
    :class:`PhysicsRule`."""

    def __init__(self, rule: PhysicsRule) -> None:
        self._rule = rule

    def attribute(self, flags: Mapping[str, bool], window: Window) -> dict[str, AttributionResult]:
        """Attribute each channel in ``flags``.

        ``flags`` maps channel -> anomaly flag (bool). The physics rule is
        consulted once per window (only if at least one channel is flagged). A
        flagged channel that the rule names as the violation suspect is an
        ``attack``; any other flagged channel is a ``fault``; unflagged channels
        are ``none``."""
        for ch in flags:
            if ch not in CHANNELS:
                raise ValueError(f"unknown channel {ch!r}; must be one of {CHANNELS}")

        check: PhysicsCheck | None = None
        if any(flags.values()):
            check = self._rule.check(window)

        out: dict[str, AttributionResult] = {}
        for ch, flagged in flags.items():
            if not flagged:
                out[ch] = AttributionResult(ch, Attribution.none, REASON_NONE)
                continue
            if check is not None and check.violated and check.suspect_channel == ch:
                reason = check.reason or REASON_ATTACK_FALLBACK
                out[ch] = AttributionResult(ch, Attribution.attack, reason)
            else:
                out[ch] = AttributionResult(ch, Attribution.fault, REASON_FAULT)
        return out
