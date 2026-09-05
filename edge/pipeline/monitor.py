"""Live monitoring-only P2 wiring (P0 gap-closure item 1).

Bridges the real acquisition loop (``edge/main.py`` → ``AcquisitionRuntime``'s
``on_healthy_frame`` seam) to the existing, UNMODIFIED ``P2Pipeline`` —
observation only. This module does not isolate a channel, does not actuate,
does not publish a decision/ledger message, and does not import or call
anything in ``edge/pipeline/self_heal.py`` or ``edge/pipeline/cycle.py``. It
only calculates and reports ``WindowOutcome`` (preprocessing, anomaly, trust,
attribution) for the caller to log.

``ConsistencyProvider`` ("c") is the one P2 component that raises before use
if unfit (``edge/trust/c_consistency.py``: ``record_window()`` requires
``fit()`` first, unconditionally called every window by
``P2Pipeline.process()``). Its ``fit()`` computes one RMS-z-score PER FIT
WINDOW and stores them sorted for an empirical-CDF lookup — fitting on a
single window (this module's original design) gives that sorted list length
1, so every subsequent ``record_window()`` call's severity can only rank as
0 or 1: ``c`` collapses to a binary {0.0, 1.0} signal for the entire session,
even on perfectly clean, in-distribution data (verified empirically before
this fix — see the conversation record; NOT a defect in
``ConsistencyProvider`` itself, which behaves exactly as documented).

Fix: bootstrap-fit on ``fit_window_count`` (REQUIRED, no default — see
``edge/main.py``'s ``P2_FIT_WINDOW_COUNT`` env var) clean live windows
instead of one. The buffer needed to produce exactly ``fit_window_count``
windows from ``Preprocessor.process()`` is:

    fit_buffer_size = preprocessor.window_size + (fit_window_count - 1) * preprocessor.step

This is derived directly from ``Preprocessor.process()``'s own loop
(``edge/anomaly/preprocess.py``): windows start at ``0, step, 2*step, ...``
and a window is produced while ``start + window_size <= n``, so the count of
windows produced from ``n`` frames is ``floor((n - window_size) / step) + 1``.
Solving for the smallest ``n`` giving exactly ``fit_window_count`` windows
gives the formula above; verified empirically against the real
``Preprocessor.process()`` for several (window_size, step, count) triples,
including the ``n-1 -> count-1`` boundary, before this fix was written.

Every other component this module composes needs no fit corpus at all:
  - ``NullDetector`` never flags (``edge/anomaly/detector.py``), so
    ``ChannelFlagPolicy.flags()`` always takes its "not anomaly.flag"
    early-return branch (``edge/anomaly/policy.py``) — it never reaches the
    branch that would raise if unfitted.
  - ``AttributionEngine.attribute()`` only calls ``PhysicsRule.check()``
    ``if any(flags.values())`` (``edge/anomaly/attribution.py``) — with
    every flag always False, an unfitted ``TrendSignPhysicsRule`` is never
    invoked.
This is a direct, structural consequence of the existing code (verified by
reading it), not a workaround invented for this module.

``ConsistencyProvider`` itself is untouched — this fix only changes how much
data ``LiveP2Monitor`` collects before calling its existing, unmodified
``fit()`` method.

RAW-VALUE PLUMBING (integration-readiness prep, still observe-only): each
emitted ``WindowOutcome`` is optionally paired with the exact raw (pre-
normalization) per-channel values from the SAME buffered frames that
produced it, via the separate ``on_raw_values`` callback below.
``Preprocessor``/``P2Pipeline`` discard raw values while building a
``Window`` (min-max normalized only) — this is the one place upstream of
that where the true ``TelemetryMessage.sensors`` values are still available.
This is preparatory plumbing only: nothing in this module (or anywhere it
is called from) consumes these values for isolation, substitution,
divergence, or actuation — see the investigation record for why that
remains blocked on a genuinely validated digital-twin and a real numeric
divergence-comparison value, neither of which exists yet. ``on_outcome``'s
existing single-argument shape is completely unchanged for compatibility;
``on_raw_values`` is a new,
independent, optional hook (default ``None``, meaning existing callers see
byte-identical behavior).
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.pipeline import P2Pipeline, WindowOutcome
from edge.anomaly.preprocess import Preprocessor
from edge.trust.c_consistency import ConsistencyProvider

log = logging.getLogger("shtapm.edge.p2monitor")


@dataclass(frozen=True)
class RawChannelValues:
    """The most recent raw (pre-normalization) per-channel sensor values
    for the EXACT window that produced the paired ``WindowOutcome`` —
    sourced directly from the last buffered ``TelemetryMessage`` in that
    window, never reconstructed, renormalized, or otherwise derived.

    ``ts``/``sample_seq`` are the originating frame's own wire-contract
    fields (already published telemetry, not sensitive) — included so a
    caller/log line can verify correspondence to the paired outcome without
    re-deriving it.
    """

    ts: str
    sample_seq: int
    values: dict[str, float]


class LiveP2Monitor:
    """Warms up on ``fit_window_count`` live windows (fits
    ``ConsistencyProvider`` once, no output emitted before this completes),
    then runs the real ``P2Pipeline`` on one new sliding window per tick
    (step=1 contiguous windows at the live-loop level, matching
    ``Preprocessor``'s own semantics) with no change to
    ``Preprocessor``/``P2Pipeline``/``ConsistencyProvider``.

    Call ``on_frame(frame)`` once per healthy tick — designed to be passed
    directly as ``AcquisitionRuntime(..., on_healthy_frame=monitor.on_frame)``.
    """

    def __init__(
        self,
        *,
        preprocessor: Preprocessor,
        pipeline: P2Pipeline,
        c_provider: ConsistencyProvider,
        fit_window_count: int,
        on_outcome: Callable[[WindowOutcome], None] = lambda outcome: None,
        on_raw_values: Callable[[WindowOutcome, RawChannelValues], None] | None = None,
    ) -> None:
        if fit_window_count <= 0:
            raise ValueError(f"fit_window_count must be > 0, got {fit_window_count}")
        self._preprocessor = preprocessor
        self._pipeline = pipeline
        self._c_provider = c_provider
        self._on_outcome = on_outcome
        self._on_raw_values = on_raw_values
        self._fit_buffer_size = (
            preprocessor.window_size + (fit_window_count - 1) * preprocessor.step
        )
        # Warm-up phase: plain list, accumulated up to exactly
        # _fit_buffer_size frames, never more (we transition out of this
        # phase the instant that size is reached). Normal phase: a
        # window_size-capped deque, created only once warm-up completes.
        self._warmup_buffer: list[TelemetryMessage] = []
        self._buffer: deque[TelemetryMessage] | None = None

    def on_frame(self, frame: TelemetryMessage) -> None:
        """Feed one healthy telemetry frame (monitoring-only: no isolation,
        no actuation, no publish)."""
        if self._buffer is not None:
            self._buffer.append(frame)
            self._emit(list(self._buffer))
            return

        self._warmup_buffer.append(frame)
        if len(self._warmup_buffer) < self._fit_buffer_size:
            return

        fit_windows = self._preprocessor.process(self._warmup_buffer)  # exactly fit_window_count
        self._c_provider.fit(fit_windows)
        log.info("P2 monitor: ConsistencyProvider fit on %d clean live windows", len(fit_windows))

        # Transition to the steady-state rolling buffer, seeded with the
        # most recent window_size frames (the same frames the last fit
        # window covered) so normal monitoring continues immediately.
        window_size = self._preprocessor.window_size
        self._buffer = deque(self._warmup_buffer[-window_size:], maxlen=window_size)
        self._warmup_buffer = []  # release; no longer needed

        self._emit(list(self._buffer))

    def _emit(self, frames: list[TelemetryMessage]) -> None:
        for outcome in self._pipeline.process(frames):  # exactly one, len(frames) == window_size
            self._on_outcome(outcome)
            if self._on_raw_values is not None:
                self._on_raw_values(outcome, self._raw_values_for(frames))

    @staticmethod
    def _raw_values_for(frames: list[TelemetryMessage]) -> RawChannelValues:
        """The exact window's most recent (last-buffered) raw sample —
        never the normalized ``Window.features``."""
        latest = frames[-1]
        return RawChannelValues(
            ts=latest.ts,
            sample_seq=latest.sample_seq,
            values={ch: getattr(latest.sensors, ch) for ch in CHANNELS},
        )
