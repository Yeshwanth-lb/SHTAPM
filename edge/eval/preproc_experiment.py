"""Normalization-variant experiment (DIAGNOSTIC ONLY — no production change).

Compares three normalization strategies feeding the UNCHANGED
:class:`IsolationForestDetector`, purely to understand the two findings from the
IF probe (22% clean FP; per-window min-max erases additive bias). It builds
:class:`Window` objects locally with each variant's normalization; it does NOT
touch ``edge/anomaly/preprocess.py`` or any production code.

Variants:
  A. per-window min-max        (CURRENT production behaviour; reuses the
                                production ``min_max_normalize``)
  B. train-fit global min-max  (per-channel min/max from the CLEAN TRAINING
                                frames, applied to every window)
  C. train-fit z-score         (per-channel mean/std from the CLEAN TRAINING
                                frames, applied to every window)

Everything is reused from ``if_eval`` (seeds, injection fixtures, threshold,
overlap/inside helpers). All magnitudes + the flag threshold remain EVALUATION
FIXTURES ONLY — not project specifications. No P2 acceptance claim is made; real
behaviour stays dataset-gated (SWaT/WADI/TEP, U07).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.preprocess import Window, min_max_normalize
from edge.eval.if_eval import (
    BASELINE_FRAMES,
    BASELINE_SEED,
    FLAG_THRESHOLD_FIXTURE,
    IF_RANDOM_STATE,
    INJ_DURATION,
    INJ_ONSET,
    STREAM_FRAMES,
    TRAIN_FRAMES,
    TRAIN_SEED,
    _injections,
    _inside,
    _overlaps,
    clean_stream,
)

WINDOW = 30
STEP = 1

# A normalizer maps a raw per-channel window slice -> normalized values, using
# optional per-channel training parameters.
Normalizer = Callable[[list[float], str], list[float]]


def _raw_series(frames: list[TelemetryMessage]) -> dict[str, list[float]]:
    return {ch: [float(getattr(f.sensors, ch)) for f in frames] for ch in CHANNELS}


def _windows(frames: list[TelemetryMessage], normalize: Normalizer) -> list[Window]:
    raw = _raw_series(frames)
    n = len(frames)
    out: list[Window] = []
    start = 0
    while start + WINDOW <= n:
        end = start + WINDOW
        feats = {ch: tuple(normalize(raw[ch][start:end], ch)) for ch in CHANNELS}
        out.append(Window(start_index=start, end_index=end, features=feats))
        start += STEP
    return out


# --- variant A: per-window min-max (production behaviour) --------------------
def _norm_per_window(slice_vals: list[float], channel: str) -> list[float]:
    return min_max_normalize(slice_vals)  # reuse production function verbatim


# --- variant B: train-fit global min-max ------------------------------------
def _make_global_minmax(train: list[TelemetryMessage]) -> Normalizer:
    raw = _raw_series(train)
    lo = {ch: min(raw[ch]) for ch in CHANNELS}
    hi = {ch: max(raw[ch]) for ch in CHANNELS}

    def norm(slice_vals: list[float], channel: str) -> list[float]:
        span = hi[channel] - lo[channel]
        if span == 0:
            return [0.0] * len(slice_vals)
        return [(v - lo[channel]) / span for v in slice_vals]

    return norm


# --- variant C: train-fit z-score -------------------------------------------
def _make_zscore(train: list[TelemetryMessage]) -> Normalizer:
    raw = _raw_series(train)
    mean = {ch: statistics.fmean(raw[ch]) for ch in CHANNELS}
    std = {ch: statistics.pstdev(raw[ch]) for ch in CHANNELS}

    def norm(slice_vals: list[float], channel: str) -> list[float]:
        s = std[channel]
        if s == 0:
            return [0.0] * len(slice_vals)
        return [(v - mean[channel]) / s for v in slice_vals]

    return norm


@dataclass
class VariantCase:
    injection: str
    channel: str
    inside_peak: float | None
    overlap_peak: float
    flagged_overlap: int
    detected: bool


@dataclass
class VariantResult:
    name: str
    clean_n: int
    clean_sev_min: float
    clean_sev_median: float
    clean_sev_max: float
    clean_false_positives: int
    clean_fp_rate: float
    cases: list[VariantCase]


def _median(vals: list[float]) -> float:
    return statistics.median(vals) if vals else 0.0


def _evaluate_variant(name: str, normalize: Normalizer) -> VariantResult:
    train = clean_stream(TRAIN_FRAMES, TRAIN_SEED)
    detector = IsolationForestDetector(
        flag_threshold=FLAG_THRESHOLD_FIXTURE, random_state=IF_RANDOM_STATE
    )
    detector.fit(_windows(train, normalize))

    base = _windows(clean_stream(BASELINE_FRAMES, BASELINE_SEED), normalize)
    base_sev = sorted(detector.score(w) for w in base)
    fp = sum(1 for s in base_sev if s >= FLAG_THRESHOLD_FIXTURE)

    cases: list[VariantCase] = []
    for cname, injection, _fixture in _injections():
        injected = injection.apply(clean_stream(STREAM_FRAMES, TRAIN_SEED)).frames
        windows = _windows(injected, normalize)
        overlap = [w for w in windows if _overlaps(w, INJ_ONSET, INJ_DURATION)]
        inside = [w for w in windows if _inside(w, INJ_ONSET, INJ_DURATION)]
        sev = [detector.score(w) for w in overlap]
        inside_peak = max((detector.score(w) for w in inside), default=None)
        n_flag = sum(1 for s in sev if s >= FLAG_THRESHOLD_FIXTURE)
        cases.append(
            VariantCase(
                injection=cname,
                channel=injection.channel,
                inside_peak=inside_peak,
                overlap_peak=max(sev) if sev else 0.0,
                flagged_overlap=n_flag,
                detected=n_flag > 0,
            )
        )

    return VariantResult(
        name=name,
        clean_n=len(base_sev),
        clean_sev_min=base_sev[0],
        clean_sev_median=_median(base_sev),
        clean_sev_max=base_sev[-1],
        clean_false_positives=fp,
        clean_fp_rate=fp / len(base_sev) if base_sev else 0.0,
        cases=cases,
    )


def run_experiment() -> list[VariantResult]:
    """Deterministic run of all three variants."""
    train = clean_stream(TRAIN_FRAMES, TRAIN_SEED)
    return [
        _evaluate_variant("A_per_window_minmax", _norm_per_window),
        _evaluate_variant("B_global_minmax", _make_global_minmax(train)),
        _evaluate_variant("C_zscore", _make_zscore(train)),
    ]


def format_report(results: list[VariantResult]) -> str:
    thr = FLAG_THRESHOLD_FIXTURE
    lines: list[str] = []
    lines.append("=== P2 normalization-variant experiment (DIAGNOSTIC, NOT acceptance) ===")
    lines.append(
        f"FIXTURES: train_seed={TRAIN_SEED} baseline_seed={BASELINE_SEED} "
        f"if_random_state={IF_RANDOM_STATE} window={WINDOW} threshold(EVAL)={thr}"
    )
    for r in results:
        lines.append("")
        lines.append(f"## Variant {r.name}")
        lines.append(
            f"clean: n={r.clean_n} sev[min/med/max]="
            f"{r.clean_sev_min:.3f}/{r.clean_sev_median:.3f}/{r.clean_sev_max:.3f} "
            f"FP={r.clean_false_positives} fp_rate={r.clean_fp_rate:.3f} (>= {thr})"
        )
        lines.append(
            f"{'injection':14} {'inside_pk':>9} {'overlap_pk':>10} {'flagged':>7} {'detected':>8}"
        )
        for c in r.cases:
            inside = "n/a" if c.inside_peak is None else f"{c.inside_peak:.3f}"
            lines.append(
                f"{c.injection:14} {inside:>9} {c.overlap_peak:>10.3f} "
                f"{c.flagged_overlap:>7} {str(c.detected):>8}"
            )
    lines.append("")
    lines.append(
        "NOTE: severity = IF empirical-CDF vs each variant's own clean-train scores; "
        "'detected' = peak >= the EVALUATION-FIXTURE threshold, NOT a P2 acceptance "
        "result. inside_pk = steady-state (fully-injected) windows. Observations are "
        "for the INDEPENDENT-channel simulator only (no cross-sensor physics) and do "
        "NOT predict SWaT/WADI/TEP behaviour."
    )
    return "\n".join(lines)


def main() -> None:
    print(format_report(run_experiment()))


if __name__ == "__main__":
    main()
