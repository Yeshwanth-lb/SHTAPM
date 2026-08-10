"""Multivariate Isolation Forest detector (P2 · FR-A1).

Concrete :class:`~edge.anomaly.detector.AnomalyDetector` backed by a single
scikit-learn :class:`~sklearn.ensemble.IsolationForest` over the whole
six-channel window.

Design (approved D-A / D-B):
  * Feature (D-A): each 30x6 :class:`~edge.anomaly.preprocess.Window` is flattened
    (``as_matrix()`` -> row-major) into ONE 180-dim observation. One IF sample =
    one window (FR-A1 "per window"). Single multivariate model over all channels.
  * Severity (D-B): ``fit()`` stores the clean-baseline anomaly-score
    distribution; ``score()`` returns the empirical-CDF / rank position of a
    window's anomaly score within that distribution, in [0, 1]. Higher = more
    anomalous. No magic constant.
  * ``flag()`` = ``severity >= flag_threshold``. ``flag_threshold`` is a REQUIRED
    constructor argument — no project value is chosen or baked here.

Undocumented IF hyperparameters (``n_estimators``, ``max_samples``,
``max_features``, ``contamination``) are exposed as optional passthroughs: when
left ``None`` they are NOT forwarded, so scikit-learn's own library defaults
apply (not a SHTAPM specification). ``random_state`` is exposed for
deterministic runs.

Scope: no ChannelFlagPolicy localization, no c/k/h, no physics, no attribution,
no dataset/attack-specific thresholds. The frozen contract is untouched.

Dependency: scikit-learn (edge P2 runtime dep — ``edge/requirements.txt`` pins
``scikit-learn==1.4.*`` per TRD §02.2). Imported at module load, so import this
module only where scikit-learn is available.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from sklearn.ensemble import IsolationForest

from edge.anomaly.preprocess import Window


class IsolationForestDetector:
    """AnomalyDetector implementation using one multivariate Isolation Forest."""

    def __init__(
        self,
        *,
        flag_threshold: float,
        n_estimators: int | None = None,
        max_samples: int | float | str | None = None,
        max_features: int | float | None = None,
        contamination: float | str | None = None,
        random_state: int | None = None,
    ) -> None:
        if not (0.0 <= flag_threshold <= 1.0):
            raise ValueError(f"flag_threshold must be in [0, 1], got {flag_threshold}")
        self.flag_threshold = flag_threshold

        # Only forward hyperparameters the caller set; otherwise sklearn's own
        # library defaults apply (NOT a SHTAPM spec value).
        kwargs: dict[str, object] = {}
        if n_estimators is not None:
            kwargs["n_estimators"] = n_estimators
        if max_samples is not None:
            kwargs["max_samples"] = max_samples
        if max_features is not None:
            kwargs["max_features"] = max_features
        if contamination is not None:
            kwargs["contamination"] = contamination
        if random_state is not None:
            kwargs["random_state"] = random_state

        self._model = IsolationForest(**kwargs)
        self._train_anom_sorted: np.ndarray | None = None

    @property
    def fitted(self) -> bool:
        return self._train_anom_sorted is not None

    @staticmethod
    def _features(window: Window) -> np.ndarray:
        """Flatten a 30x6 window to a 1-D 180-length vector (row-major)."""
        return np.asarray(window.as_matrix(), dtype=float).reshape(-1)

    def _matrix(self, windows: Sequence[Window]) -> np.ndarray:
        return np.stack([self._features(w) for w in windows])

    def _anomaly_scores(self, x: np.ndarray) -> np.ndarray:
        """Anomaly score where HIGHER = more anomalous.

        ``score_samples`` returns higher-is-more-normal, so negate it."""
        return -self._model.score_samples(x)

    def fit(self, windows: Sequence[Window]) -> None:
        """Train on clean-baseline windows and store their anomaly-score
        distribution for severity calibration (FR-A1)."""
        windows = list(windows)
        if not windows:
            raise ValueError("fit() requires at least one clean-baseline window")
        x = self._matrix(windows)
        self._model.fit(x)
        self._train_anom_sorted = np.sort(self._anomaly_scores(x))

    def _require_fitted(self) -> np.ndarray:
        if self._train_anom_sorted is None:
            raise RuntimeError("detector is not fitted; call fit() first")
        return self._train_anom_sorted

    def score(self, window: Window) -> float:
        """Severity in [0, 1] = empirical-CDF / rank of this window's anomaly
        score within the clean-baseline distribution. Higher = more anomalous."""
        train = self._require_fitted()
        a = float(self._anomaly_scores(self._features(window).reshape(1, -1))[0])
        # fraction of clean windows at most as anomalous as this one
        rank = int(np.searchsorted(train, a, side="right"))
        return rank / len(train)

    def flag(self, window: Window) -> bool:
        """Anomalous iff severity meets the explicit configured threshold."""
        return self.score(window) >= self.flag_threshold
