"""Anomaly-detector interface + result structures + a NullDetector (P2).

Defines the seam the P2 pipeline depends on so the real Isolation Forest
(FR-A1) can be dropped in later WITHOUT choosing hyperparameters or a flag
threshold now. This module contains NO Isolation Forest, no thresholds, and no
attribution/physics/trust logic.

``AnomalyResult`` carries only the FR-A3 anomaly fields this stage owns —
``flag`` + ``severity`` (in [0,1]). It is an internal edge structure, NOT the
frozen wire ``AnomalyInfo`` (which also needs attribution/reason, out of scope);
the frozen contract is untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from edge.anomaly.preprocess import Window


@dataclass(frozen=True)
class AnomalyResult:
    """Per-window anomaly outcome (internal; not the wire contract)."""

    flag: bool
    severity: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.severity <= 1.0):
            raise ValueError(f"severity must be in [0, 1], got {self.severity}")


@runtime_checkable
class AnomalyDetector(Protocol):
    """The detector seam. Implementations map a preprocessed :class:`Window` to
    a severity in [0,1] and a boolean flag.

    Contract only — it deliberately says nothing about the algorithm, features,
    contamination, or flag threshold. Those are chosen when the real detector is
    implemented and tuned (requires dataset; out of scope here)."""

    def fit(self, windows: Sequence[Window]) -> None:
        """Train on clean-baseline windows (FR-A1)."""
        ...

    def score(self, window: Window) -> float:
        """Anomaly severity in [0,1]."""
        ...

    def flag(self, window: Window) -> bool:
        """Whether the window is anomalous."""
        ...


def detect(detector: AnomalyDetector, window: Window) -> AnomalyResult:
    """Run a detector over one window and package the outcome."""
    return AnomalyResult(flag=detector.flag(window), severity=detector.score(window))


class NullDetector:
    """Placeholder detector for wiring/tests: never flags, severity always 0.0.

    It embodies NO detection heuristic and NO threshold — it exists so the
    pipeline and its tests can run before the real Isolation Forest is built and
    tuned. It must never be mistaken for a working detector.
    """

    def __init__(self) -> None:
        self.fitted = False
        self.fit_count = 0

    def fit(self, windows: Sequence[Window]) -> None:
        self.fitted = True
        self.fit_count = len(windows)

    def score(self, window: Window) -> float:
        return 0.0

    def flag(self, window: Window) -> bool:
        return False
