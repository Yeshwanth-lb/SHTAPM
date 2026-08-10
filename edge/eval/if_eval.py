"""Isolation Forest behaviour probe on the simulator (hardware-free, diagnostic).

Pipeline: simulator clean stream -> synthetic §12.4 injection -> documented
preprocessing (30-sample windows) -> real IsolationForestDetector -> severity.

NOTHING here is a project specification:
  * every injection magnitude/duration is an EVALUATION FIXTURE (labelled),
  * the flag threshold is an EVALUATION FIXTURE (labelled) used only to derive
    flag/false-positive counts for this probe — it is NOT wired into the
    production detector and is NOT a project default,
  * the detector, injections, preprocessing, and simulator are used AS-IS; none
    is modified to make any case pass.

Determinism: fixed simulator seed, fixed IF ``random_state``, and timestamps
derived from the sample index (no wall clock).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.contracts import TelemetryMessage

from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.preprocess import Preprocessor, Window
from edge.injection.injections import (
    BiasFDI,
    ConstantSpoof,
    Drift,
    Injection,
    RampFDI,
    Replay,
    Spike,
    StuckAt,
)
from simulator.generator import TelemetrySimulator

# ---- EVALUATION FIXTURES ONLY (arbitrary diagnostic values, NOT specs) ------
TRAIN_SEED = 1337  # simulator default; clean training stream
BASELINE_SEED = 2024  # held-out clean stream for false-positive measurement
IF_RANDOM_STATE = 0  # determinism only
TRAIN_FRAMES = 300
BASELINE_FRAMES = 200
STREAM_FRAMES = 200
INJ_ONSET = 80
INJ_DURATION = 60
FLAG_THRESHOLD_FIXTURE = 0.95  # eval-only; NOT a project threshold
# Identity filters (median_kernel=1, alpha=1.0) so the probe adds no undocumented
# smoothing; window_size stays the documented 30.
PREPROC = dict(median_kernel=1, low_pass_alpha=1.0, window_size=30, step=1)


def _ts(i: int) -> str:
    """Deterministic ISO timestamp from the sample index (no wall clock)."""
    return f"2026-08-10T00:{i // 60:02d}:{i % 60:02d}.000Z"


def clean_stream(n: int, seed: int) -> list[TelemetryMessage]:
    sim = TelemetrySimulator(seed=seed)
    return sim.generate(n, [_ts(i) for i in range(n)])


def to_windows(frames: list[TelemetryMessage]) -> list[Window]:
    return Preprocessor(**PREPROC).process(frames)


def _overlaps(w: Window, onset: int, duration: int) -> bool:
    return w.start_index < onset + duration and w.end_index > onset


def _inside(w: Window, onset: int, duration: int) -> bool:
    return onset <= w.start_index and w.end_index <= onset + duration


@dataclass
class CaseResult:
    injection: str
    channel: str
    fixture: dict
    n_windows_overlap: int
    peak_severity_overlap: float
    peak_window_overlap: tuple[int, int]
    peak_severity_inside: float | None
    n_flagged_overlap: int
    detected: bool


@dataclass
class BaselineResult:
    n_windows: int
    severity_min: float
    severity_median: float
    severity_max: float
    false_positives: int
    fp_rate: float
    threshold_fixture: float


@dataclass
class EvalReport:
    baseline: BaselineResult
    cases: list[CaseResult] = field(default_factory=list)


def _injections() -> list[tuple[str, Injection, dict]]:
    """The 7 hardware-free §12.4 injections with EVALUATION-FIXTURE params."""
    o, d = INJ_ONSET, INJ_DURATION
    return [
        ("drift", Drift(channel="pressure", onset=o, duration=d, rate=0.5), {"rate": 0.5}),
        (
            "spike",
            Spike(channel="vibration", onset=o, duration=1, amplitude=50.0),
            {"amplitude": 50.0},
        ),
        ("stuck_at", StuckAt(channel="pressure", onset=o, duration=d), {"held": "onset value"}),
        ("bias_fdi", BiasFDI(channel="pressure", onset=o, duration=d, bias=20.0), {"bias": 20.0}),
        ("ramp_fdi", RampFDI(channel="pressure", onset=o, duration=d, slope=0.5), {"slope": 0.5}),
        (
            "replay",
            Replay(channel="pressure", onset=o, duration=d, source_onset=0),
            {"source_onset": 0},
        ),
        (
            "constant_spoof",
            ConstantSpoof(channel="pressure", onset=o, duration=d, value=1013.0),
            {"value": 1013.0},
        ),
    ]


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return sorted_vals[idx]


def run_eval() -> EvalReport:
    """Fit on clean baseline, then score clean + each injection. Deterministic."""
    detector = IsolationForestDetector(
        flag_threshold=FLAG_THRESHOLD_FIXTURE, random_state=IF_RANDOM_STATE
    )
    detector.fit(to_windows(clean_stream(TRAIN_FRAMES, TRAIN_SEED)))

    # Held-out clean baseline -> false-positive measurement.
    base_windows = to_windows(clean_stream(BASELINE_FRAMES, BASELINE_SEED))
    base_sev = sorted(detector.score(w) for w in base_windows)
    fp = sum(1 for s in base_sev if s >= FLAG_THRESHOLD_FIXTURE)
    baseline = BaselineResult(
        n_windows=len(base_sev),
        severity_min=base_sev[0],
        severity_median=_percentile(base_sev, 0.5),
        severity_max=base_sev[-1],
        false_positives=fp,
        fp_rate=fp / len(base_sev) if base_sev else 0.0,
        threshold_fixture=FLAG_THRESHOLD_FIXTURE,
    )

    cases: list[CaseResult] = []
    for name, injection, fixture in _injections():
        clean = clean_stream(STREAM_FRAMES, TRAIN_SEED)
        injected = injection.apply(clean).frames
        windows = to_windows(injected)
        overlap = [w for w in windows if _overlaps(w, INJ_ONSET, INJ_DURATION)]
        inside = [w for w in windows if _inside(w, INJ_ONSET, INJ_DURATION)]
        sev = [(w, detector.score(w)) for w in overlap]
        peak_w, peak_s = max(sev, key=lambda t: t[1])
        inside_peak = max((detector.score(w) for w in inside), default=None)
        n_flag = sum(1 for _, s in sev if s >= FLAG_THRESHOLD_FIXTURE)
        cases.append(
            CaseResult(
                injection=name,
                channel=injection.channel,
                fixture=fixture,
                n_windows_overlap=len(overlap),
                peak_severity_overlap=peak_s,
                peak_window_overlap=(peak_w.start_index, peak_w.end_index),
                peak_severity_inside=inside_peak,
                n_flagged_overlap=n_flag,
                detected=n_flag > 0,
            )
        )
    return EvalReport(baseline=baseline, cases=cases)


def format_report(report: EvalReport) -> str:
    thr = report.baseline.threshold_fixture
    lines: list[str] = []
    lines.append("=== P2 Isolation Forest behaviour probe (diagnostic, NOT acceptance) ===")
    lines.append(
        f"FIXTURES: train_seed={TRAIN_SEED} baseline_seed={BASELINE_SEED} "
        f"if_random_state={IF_RANDOM_STATE} window=30 threshold(EVAL)={thr}"
    )
    b = report.baseline
    lines.append("")
    lines.append("-- Clean held-out baseline (false positives) --")
    lines.append(
        f"windows={b.n_windows} severity[min/median/max]="
        f"{b.severity_min:.3f}/{b.severity_median:.3f}/{b.severity_max:.3f} "
        f"false_positives={b.false_positives} fp_rate={b.fp_rate:.3f} (>= {thr})"
    )
    lines.append("")
    lines.append("-- Injection cases (peak severity over injected windows) --")
    header = (
        f"{'injection':14} {'channel':11} {'overlap_pk':>10} {'inside_pk':>9} "
        f"{'flagged':>7} {'detected':>8}  fixture (EVAL ONLY)"
    )
    lines.append(header)
    for c in report.cases:
        inside = "n/a" if c.peak_severity_inside is None else f"{c.peak_severity_inside:.3f}"
        lines.append(
            f"{c.injection:14} {c.channel:11} {c.peak_severity_overlap:>10.3f} "
            f"{inside:>9} {c.n_flagged_overlap:>7} {str(c.detected):>8}  {c.fixture}"
        )
    lines.append("")
    lines.append(
        "NOTE: 'detected' means peak severity >= the EVALUATION-FIXTURE threshold "
        f"{thr}; it is NOT a P2 acceptance result. Per-window min-max normalization "
        "removes constant additive offsets within a fully-injected window, and the "
        "simulator generates channels INDEPENDENTLY (no cross-sensor physics), so a "
        "plausible constant-value spoof carries no cross-channel signal here. Any "
        "constant_spoof/stuck_at detection is a flat-vs-noisy shape artifact of "
        "normalization, NOT physics-based spoof detection, and does NOT indicate "
        "SWaT/WADI/TEP behaviour. Cross-sensor spoof/attribution stays dataset-gated."
    )
    return "\n".join(lines)


def main() -> None:
    print(format_report(run_eval()))


if __name__ == "__main__":
    main()
