"""Documented P2 preprocessing pipeline (FR-P1/FR-P2; PRD §20 P2 tasks).

Turns a clean :class:`~app.schemas.contracts.TelemetryMessage` stream into
fixed-size, per-channel-normalized :class:`Window` objects for the anomaly
detector. Steps, in the documented order:

    median filter -> low-pass filter -> 30-sample windows -> min-max normalize

Only ``window_size`` has a documented default (30 samples — Doc05 ``thresholds``
/ ``edge/config/device.yaml``). The smoothing parameters (median kernel,
low-pass alpha) are **required caller arguments** — the documents name the
filters but specify no kernel/alpha, so none is invented here. Setting
``median_kernel=1`` and ``low_pass_alpha=1.0`` makes both filters the identity,
so the caller is never forced into an undocumented amount of smoothing.

Min-max is computed **per window** (each window scaled to [0,1] by its own
min/max) so no external/global scaling constant is invented. A flat window
(max == min) maps to all-zeros.

No Isolation Forest, thresholds, physics, trust signals, or attribution here.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from app.schemas.contracts import CHANNELS, TelemetryMessage


def median_filter(series: list[float], kernel: int) -> list[float]:
    """Sliding-median smoothing with an odd ``kernel`` (truncated at edges).
    ``kernel == 1`` is the identity."""
    if kernel < 1 or kernel % 2 == 0:
        raise ValueError(f"kernel must be an odd positive int, got {kernel}")
    if kernel == 1:
        return list(series)
    half = kernel // 2
    n = len(series)
    out: list[float] = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out.append(float(statistics.median(series[lo:hi])))
    return out


def low_pass_filter(series: list[float], alpha: float) -> list[float]:
    """First-order EMA low-pass. ``alpha`` in (0, 1]; ``alpha == 1`` is the
    identity (output follows the input exactly)."""
    if not (0.0 < alpha <= 1.0):
        raise ValueError(f"alpha must be in (0, 1], got {alpha}")
    out: list[float] = []
    prev: float | None = None
    for x in series:
        prev = float(x) if prev is None else alpha * float(x) + (1.0 - alpha) * prev
        out.append(prev)
    return out


def min_max_normalize(values: list[float]) -> list[float]:
    """Scale to [0, 1] by the sequence's own min/max. A flat sequence
    (max == min) maps to all-zeros (defined, not a tunable threshold)."""
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [0.0] * len(values)
    span = hi - lo
    return [(v - lo) / span for v in values]


@dataclass(frozen=True)
class Window:
    """One preprocessed window: per-channel normalized series of length
    ``end_index - start_index``. ``end_index`` is exclusive."""

    start_index: int
    end_index: int
    features: dict[str, tuple[float, ...]]

    @property
    def size(self) -> int:
        return self.end_index - self.start_index

    def as_matrix(self) -> list[list[float]]:
        """Rows = samples, columns = channels in the frozen ``CHANNELS`` order.
        Convenience for a future array-based detector; no detector logic here."""
        cols = [self.features[ch] for ch in CHANNELS]
        return [list(row) for row in zip(*cols, strict=True)]


@dataclass(frozen=True)
class Preprocessor:
    """Composes the documented pipeline. ``median_kernel`` and
    ``low_pass_alpha`` are required (no invented spec defaults); ``window_size``
    defaults to the documented 30 samples."""

    median_kernel: int
    low_pass_alpha: float
    window_size: int = 30  # documented default (Doc05 thresholds; device.yaml)
    step: int = 1  # contiguous sliding windows

    def __post_init__(self) -> None:
        if self.window_size < 1:
            raise ValueError(f"window_size must be >= 1, got {self.window_size}")
        if self.step < 1:
            raise ValueError(f"step must be >= 1, got {self.step}")
        # Filter args are validated by the filter functions on use, but fail
        # fast here too so a bad Preprocessor cannot be constructed.
        if self.median_kernel < 1 or self.median_kernel % 2 == 0:
            raise ValueError(f"median_kernel must be an odd positive int, got {self.median_kernel}")
        if not (0.0 < self.low_pass_alpha <= 1.0):
            raise ValueError(f"low_pass_alpha must be in (0, 1], got {self.low_pass_alpha}")

    def process(self, frames: list[TelemetryMessage]) -> list[Window]:
        """Run the pipeline. Returns one :class:`Window` per full window; if the
        stream is shorter than ``window_size`` the result is empty."""
        raw = {ch: [float(getattr(f.sensors, ch)) for f in frames] for ch in CHANNELS}
        filtered = {
            ch: low_pass_filter(median_filter(raw[ch], self.median_kernel), self.low_pass_alpha)
            for ch in CHANNELS
        }
        n = len(frames)
        windows: list[Window] = []
        start = 0
        while start + self.window_size <= n:
            end = start + self.window_size
            feats = {ch: tuple(min_max_normalize(filtered[ch][start:end])) for ch in CHANNELS}
            windows.append(Window(start_index=start, end_index=end, features=feats))
            start += self.step
        return windows
