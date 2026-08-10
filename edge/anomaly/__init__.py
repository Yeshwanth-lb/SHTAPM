"""P2 anomaly-detection foundation (interfaces + preprocessing only).

Hardware-free, dataset-free scaffolding for FR-A1: the documented preprocessing
pipeline, the :class:`AnomalyDetector` seam, a :class:`NullDetector` placeholder,
and the internal :class:`AnomalyResult` structure.

Explicitly NOT here (undecided / out of scope): the real Isolation Forest and
its hyperparameters, the flag threshold, trust signals (c/k/h), attribution
physics, and any dataset-specific rule. The frozen telemetry contract is not
touched.
"""

from edge.anomaly.detector import (
    AnomalyDetector,
    AnomalyResult,
    NullDetector,
    detect,
)
from edge.anomaly.preprocess import (
    Preprocessor,
    Window,
    low_pass_filter,
    median_filter,
    min_max_normalize,
)

__all__ = [
    "AnomalyDetector",
    "AnomalyResult",
    "NullDetector",
    "Preprocessor",
    "Window",
    "detect",
    "low_pass_filter",
    "median_filter",
    "min_max_normalize",
]
