"""SWaT.A1 detection-level ablation study (O10).

Diagnostic/offline tooling: not production, not imported by ``edge/main.py``,
not on any acceptance path.

WHY: PRD O10 asks for "results reported on SWaT/WADI with ablations vs.
baselines". ``swat_eval.py`` produced one configuration's numbers; this module
compares variants of the detection stage against each other and against a
simple baseline, on the same data, split, windows and labels.

Follows DECISIONS.md D011 exactly, reusing ``swat_eval.py`` for loading, the
D012 tag mapping, windowing, labels and event latency:
  * temporal split -- everything is fit on ``Normal_v1`` only; ``Attack_v0``
    is evaluation only (D011-F).
  * ``k`` is excluded from validation evidence (D011-C). The trust variant
    below does NOT merely hide k: it replaces ``CorrelationProvider`` with a
    constant-1.0 provider so k cannot influence the reported trust at all.
  * ``AttributionEngine`` is NOT evaluated (D011-D). The pipeline still needs
    one, so ``swat_eval``'s null rule is used and its output is never read.

VARIANTS (all window-level, non-overlapping 30-row windows, same labels):
  zscore_baseline  per-channel RMS z-score of the raw window against each
                   channel's Normal_v1 mean/std; window score = max over the
                   six channels. No ML, no min-max normalisation.
  if_identity      Isolation Forest, identity filters (= swat_eval.py and the
                   deployed edge/main.py preprocessing).
  if_median        IF with median filter kernel 5.
  if_lowpass       IF with EMA low-pass alpha 0.3.
  if_median_lowpass  both filters.
  trust_only       full P2Pipeline (identity filters, IF at 0.90); window
                   flagged if any channel's trust < 0.7 (TRUSTED_MIN), k
                   neutralised.
  if_or_trust      if_identity at 0.90 OR trust_only.
  if_global_z      IF on windows of GLOBALLY standardised raw values (train-fit
                   mean/std per channel) instead of per-window min-max: the
                   level-aware IF. Per-window min-max hides a sustained level
                   shift once a window lies wholly inside it (D034).
  max_z_iflowpass  per window, the larger of the z-score and if_lowpass
                   severities: z-score precision plus IF event coverage.

Every score-based variant turns its raw score into the same empirical-CDF
severity against its OWN Normal_v1 fit distribution, so one threshold means
the same nominal clean-flag rate for every variant. Thresholds are swept post
hoc from one pass per variant.

EVALUATION FIXTURES ONLY: median kernel 5 and low-pass alpha 0.3 are
ablation settings, not project specifications -- the project has no documented
value for either and production runs identity filters. The z-score baseline is
defined here, not in production code.

Loading the two .xlsx files takes minutes, so the six mapped tags + timestamp
+ label are cached as CSV under ``datasets/cache/`` (``datasets/`` is
gitignored: SWaT may not be redistributed).
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor, Window
from edge.eval.swat_eval import (
    ATTACK_FILENAME,
    DEFAULT_DATA_DIR,
    DEVICE_ID,
    FLAG_POLICY_TAIL_FRACTION_FIXTURE,
    IF_RANDOM_STATE,
    NORMAL_FILENAME,
    STEP,
    TAG_MAP,
    WINDOW_SIZE,
    SwatFile,
    _NullPhysicsRule,
    compute_latency,
    load_swat_file,
)
from edge.trust.beta import TRUSTED_MIN
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider

THRESHOLDS = (0.80, 0.85, 0.90, 0.95, 0.99)
PIPELINE_THRESHOLD = 0.90  # deployed edge/main.py value; used for trust variants
ABLATION_MEDIAN_KERNEL = 5
ABLATION_LOW_PASS_ALPHA = 0.3

IF_VARIANTS: dict[str, tuple[int, float]] = {
    "if_identity": (1, 1.0),
    "if_median": (ABLATION_MEDIAN_KERNEL, 1.0),
    "if_lowpass": (1, ABLATION_LOW_PASS_ALPHA),
    "if_median_lowpass": (ABLATION_MEDIAN_KERNEL, ABLATION_LOW_PASS_ALPHA),
}

_CACHE_FIELDS = ["ts", "label", *CHANNELS]


# ---------------------------------------------------------------------------
# Loading (cached)
# ---------------------------------------------------------------------------


def _cache_path(data_dir: Path, filename: str, limit: int | None) -> Path:
    suffix = "" if limit is None else f".limit{limit}"
    return data_dir / "cache" / f"{Path(filename).stem}{suffix}.csv"


def load_cached(data_dir: Path, filename: str, sheet: str, limit: int | None) -> SwatFile:
    cache = _cache_path(data_dir, filename, limit)
    if not cache.exists():
        loaded = load_swat_file(data_dir / filename, sheet, limit=limit)
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_CACHE_FIELDS)
            for frame, label in zip(loaded.frames, loaded.labels, strict=True):
                writer.writerow(
                    [frame.ts, label, *(repr(float(getattr(frame.sensors, ch))) for ch in CHANNELS)]
                )
        return loaded

    frames: list[TelemetryMessage] = []
    labels: list[str] = []
    with open(cache, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for seq, row in enumerate(reader):
            sensors = {ch: float(row[ch]) for ch in CHANNELS}
            frames.append(build_telemetry(DEVICE_ID, row["ts"], sensors, seq))
            labels.append(row["label"])
    return SwatFile(frames=frames, labels=labels)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class Metrics:
    tp: int
    fp: int
    tn: int
    fn: int
    onsets: int
    onsets_flagged: int
    onsets_within_3: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def fp_rate(self) -> float:
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else 0.0


def window_is_attack(labels: list[str], start: int, end: int) -> bool:
    return "Attack" in labels[start:end]


def score_flags(flags: list[bool], starts: list[int], labels: list[str], boundary: int) -> Metrics:
    """Window-level confusion + event-level onset detection for one variant.

    ``flags``/``starts`` are eval-region windows in order (start >= boundary).
    Event latency reuses ``swat_eval.compute_latency`` unchanged."""
    tp = fp = tn = fn = 0
    for flag, start in zip(flags, starts, strict=True):
        attack = window_is_attack(labels, start, start + WINDOW_SIZE)
        if attack and flag:
            tp += 1
        elif attack:
            fn += 1
        elif flag:
            fp += 1
        else:
            tn += 1
    outcomes = [SimpleNamespace(anomaly=SimpleNamespace(flag=f)) for f in flags]
    latency = compute_latency(outcomes, labels, boundary)
    return Metrics(
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        onsets=latency.n_onsets,
        onsets_flagged=latency.n_flagged,
        onsets_within_3=sum(1 for w in latency.latencies_windows if w <= 3),
    )


def ecdf_severity(fit_scores: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """Same empirical-CDF severity convention as ``IsolationForestDetector.score``."""
    ordered = np.sort(fit_scores)
    return np.searchsorted(ordered, scores, side="right") / len(ordered)


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def _windows(frames: list[TelemetryMessage], median_kernel: int, alpha: float) -> list[Window]:
    return Preprocessor(
        median_kernel=median_kernel, low_pass_alpha=alpha, window_size=WINDOW_SIZE, step=STEP
    ).process(frames)


def zscore_scores(
    normal: list[TelemetryMessage], combined: list[TelemetryMessage], boundary: int
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Baseline: max over channels of the window's RMS z-score (raw values)."""
    fit_raw = np.array([[float(getattr(f.sensors, ch)) for ch in CHANNELS] for f in normal])
    mean = fit_raw.mean(axis=0)
    std = fit_raw.std(axis=0) + 1e-8
    all_raw = np.array([[float(getattr(f.sensors, ch)) for ch in CHANNELS] for f in combined])
    z = (all_raw - mean) / std

    def window_scores(lo: int, hi: int) -> tuple[np.ndarray, list[int]]:
        starts = list(range(lo, hi - WINDOW_SIZE + 1, STEP))
        out = np.array([np.sqrt((z[s : s + WINDOW_SIZE] ** 2).mean(axis=0)).max() for s in starts])
        return out, starts

    fit_scores, _ = window_scores(0, boundary)
    eval_scores, eval_starts = window_scores(boundary, len(combined))
    return fit_scores, eval_scores, eval_starts


def if_severities(
    normal: list[TelemetryMessage],
    combined: list[TelemetryMessage],
    boundary: int,
    median_kernel: int,
    alpha: float,
) -> tuple[np.ndarray, list[int]]:
    """IF severity for every eval window. Filters run over the continuous
    Normal_v1 + Attack_v0 stream, exactly as ``swat_eval.run_eval`` does."""
    detector = IsolationForestDetector(
        flag_threshold=PIPELINE_THRESHOLD, random_state=IF_RANDOM_STATE
    )
    detector.fit(_windows(normal, median_kernel, alpha))
    eval_windows = [
        w for w in _windows(combined, median_kernel, alpha) if w.start_index >= boundary
    ]
    return (
        np.array([detector.score(w) for w in eval_windows]),
        [w.start_index for w in eval_windows],
    )


def _raw_matrix(frames: list[TelemetryMessage]) -> np.ndarray:
    return np.array([[float(getattr(f.sensors, ch)) for ch in CHANNELS] for f in frames])


def if_global_z_severities(
    normal: list[TelemetryMessage], combined: list[TelemetryMessage], boundary: int
) -> tuple[np.ndarray, list[int]]:
    """IF over flattened 30x6 windows of train-standardised raw values,
    batch-scored (same forest settings as the deployed detector)."""
    from sklearn.ensemble import IsolationForest

    fit_raw = _raw_matrix(normal)
    mean, std = fit_raw.mean(axis=0), fit_raw.std(axis=0) + 1e-8
    z = (_raw_matrix(combined) - mean) / std

    def mats(lo: int, hi: int) -> tuple[np.ndarray, list[int]]:
        starts = list(range(lo, hi - WINDOW_SIZE + 1, STEP))
        return np.stack([z[s : s + WINDOW_SIZE].reshape(-1) for s in starts]), starts

    fit_x, _ = mats(0, boundary)
    eval_x, eval_starts = mats(boundary, len(combined))
    model = IsolationForest(random_state=IF_RANDOM_STATE).fit(fit_x)
    return ecdf_severity(-model.score_samples(fit_x), -model.score_samples(eval_x)), eval_starts


class _NeutralK:
    """Constant k = 1.0 so the correlation signal cannot touch reported trust
    (D011-C). 1.0 is D010's own documented value for an unpaired channel."""

    def record_window(self, window: Window) -> None:
        return None

    def evaluate(self, channel: str) -> float:
        return 1.0


def trust_flags(
    normal: list[TelemetryMessage], combined: list[TelemetryMessage], boundary: int
) -> tuple[list[bool], list[bool], list[int], dict[str, float]]:
    """Run the full pipeline once; return per-window (IF flag, trust flag)."""
    fit_windows = _windows(normal, 1, 1.0)
    detector = IsolationForestDetector(
        flag_threshold=PIPELINE_THRESHOLD, random_state=IF_RANDOM_STATE
    )
    detector.fit(fit_windows)
    c_provider = ConsistencyProvider()
    c_provider.fit(fit_windows)
    flag_policy = SeverityThresholdFlagPolicy(tail_fraction=FLAG_POLICY_TAIL_FRACTION_FIXTURE)
    flag_policy.fit(fit_windows)
    pipeline = P2Pipeline(
        preprocessor=Preprocessor(
            median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW_SIZE, step=STEP
        ),
        detector=detector,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(_NullPhysicsRule()),  # output never read (D011-D)
        c_provider=c_provider,
        k_provider=_NeutralK(),
        h_provider=HReliabilityProvider(),
        flag_policy=flag_policy,
    )
    if_f: list[bool] = []
    trust_f: list[bool] = []
    starts: list[int] = []
    min_trust_eval: list[float] = []
    for o in pipeline.process(combined):
        if o.window.start_index < boundary:
            continue
        low = min(o.trust[ch].trust for ch in CHANNELS)
        if_f.append(o.anomaly.flag)
        trust_f.append(low < TRUSTED_MIN)
        starts.append(o.window.start_index)
        min_trust_eval.append(low)
    stats = {
        "min_trust_median": statistics.median(min_trust_eval),
        "share_below_trusted": sum(trust_f) / len(trust_f),
    }
    return if_f, trust_f, starts, stats


# ---------------------------------------------------------------------------
# Run + report
# ---------------------------------------------------------------------------


@dataclass
class AblationResult:
    n_fit_rows: int
    n_eval_rows: int
    n_eval_windows: int
    sweeps: dict[str, dict[float, Metrics]]  # score-based variants
    fixed: dict[str, Metrics]  # trust variants at PIPELINE_THRESHOLD
    trust_stats: dict[str, float]


def run_ablation(data_dir: Path = DEFAULT_DATA_DIR, limit: int | None = None) -> AblationResult:
    normal = load_cached(data_dir, NORMAL_FILENAME, "Normal.csv", limit)
    attack = load_cached(data_dir, ATTACK_FILENAME, "Combined Data", limit)
    combined = normal.frames + attack.frames
    labels = normal.labels + attack.labels
    boundary = len(normal.frames)

    sweeps: dict[str, dict[float, Metrics]] = {}
    n_eval_windows = 0

    fit_z, eval_z, z_starts = zscore_scores(normal.frames, combined, boundary)
    sev = ecdf_severity(fit_z, eval_z)
    sweeps["zscore_baseline"] = {
        t: score_flags([bool(s >= t) for s in sev], z_starts, labels, boundary) for t in THRESHOLDS
    }
    n_eval_windows = len(z_starts)
    print(f"[ablation] zscore_baseline done ({n_eval_windows} eval windows)", file=sys.stderr)

    z_by_start = dict(zip(z_starts, sev, strict=True))
    if_lowpass_by_start: dict[int, float] = {}
    for name, (kernel, alpha) in IF_VARIANTS.items():
        sev, starts = if_severities(normal.frames, combined, boundary, kernel, alpha)
        sweeps[name] = {
            t: score_flags([bool(s >= t) for s in sev], starts, labels, boundary)
            for t in THRESHOLDS
        }
        if name == "if_lowpass":
            if_lowpass_by_start = dict(zip(starts, sev, strict=True))
        print(f"[ablation] {name} done", file=sys.stderr)

    gz_sev, gz_starts = if_global_z_severities(normal.frames, combined, boundary)
    sweeps["if_global_z"] = {
        t: score_flags([bool(s >= t) for s in gz_sev], gz_starts, labels, boundary)
        for t in THRESHOLDS
    }
    print("[ablation] if_global_z done", file=sys.stderr)

    common = sorted(set(z_by_start) & set(if_lowpass_by_start))
    combo = [max(z_by_start[s], if_lowpass_by_start[s]) for s in common]
    sweeps["max_z_iflowpass"] = {
        t: score_flags([bool(v >= t) for v in combo], common, labels, boundary) for t in THRESHOLDS
    }
    print(f"[ablation] max_z_iflowpass done ({len(common)} aligned windows)", file=sys.stderr)

    if_f, trust_f, starts, trust_stats = trust_flags(normal.frames, combined, boundary)
    fixed = {
        "if_identity (pipeline run, check)": score_flags(if_f, starts, labels, boundary),
        "trust_only": score_flags(trust_f, starts, labels, boundary),
        "if_or_trust": score_flags(
            [a or b for a, b in zip(if_f, trust_f, strict=True)], starts, labels, boundary
        ),
    }
    print("[ablation] trust variants done", file=sys.stderr)
    return AblationResult(
        n_fit_rows=boundary,
        n_eval_rows=len(attack.frames),
        n_eval_windows=n_eval_windows,
        sweeps=sweeps,
        fixed=fixed,
        trust_stats=trust_stats,
    )


def _row(name: str, t: str, m: Metrics) -> str:
    return (
        f"  {name:<34}{t:>6}{m.tp:>6}{m.fp:>7}{m.tn:>7}{m.fn:>6}"
        f"{m.precision:>7.3f}{m.recall:>7.3f}{m.f1:>7.3f}{m.fp_rate:>7.3f}"
        f"   {m.onsets_flagged}/{m.onsets} ({m.onsets_within_3} <=3w)"
    )


def format_report(r: AblationResult) -> str:
    header = (
        f"  {'variant':<34}{'thr':>6}{'TP':>6}{'FP':>7}{'TN':>7}{'FN':>6}"
        f"{'prec':>7}{'rec':>7}{'F1':>7}{'FPR':>7}   events flagged"
    )
    lines = [
        "=== SWaT.A1 detection ablation (O10) -- DIAGNOSTIC, D011 methodology ===",
        f"D012 proxy mapping (no physical equivalence claimed): {TAG_MAP}",
        f"fit rows (Normal_v1 only): {r.n_fit_rows}   eval rows (Attack_v0): {r.n_eval_rows}   "
        f"eval windows: {r.n_eval_windows} (window={WINDOW_SIZE}, step={STEP})",
        f"ablation fixtures: median_kernel={ABLATION_MEDIAN_KERNEL}, "
        f"low_pass_alpha={ABLATION_LOW_PASS_ALPHA}",
        "",
        "-- at the deployed threshold 0.90 --",
        header,
    ]
    for name, sweep in r.sweeps.items():
        lines.append(_row(name, "0.90", sweep[PIPELINE_THRESHOLD]))
    for name, m in r.fixed.items():
        lines.append(_row(name, "0.90", m))
    lines += [
        "",
        "-- fixed thresholds chosen from CLEAN data only (no attack labels used) --",
        "   severity is each variant's empirical CDF on its own Normal_v1 fit, so 0.95 / 0.99",
        "   are nominal 5% / 1% clean-flag rates (max_z_iflowpass, a max of two, runs higher)",
        header,
    ]
    for t in (0.95, 0.99):
        for name, sweep in r.sweeps.items():
            if t in sweep:
                lines.append(_row(name, f"{t:.2f}", sweep[t]))
    lines += ["", "-- best F1 per score-based variant (threshold chosen post hoc) --", header]
    for name, sweep in r.sweeps.items():
        t, m = max(sweep.items(), key=lambda kv: kv[1].f1)
        lines.append(_row(name, f"{t:.2f}", m))
    lines += ["", "-- full sweeps --", header]
    for name, sweep in r.sweeps.items():
        for t, m in sweep.items():
            lines.append(_row(name, f"{t:.2f}", m))
    lines += [
        "",
        f"trust (k neutralised): median min-channel trust={r.trust_stats['min_trust_median']:.3f}, "
        f"share of eval windows with any channel < {TRUSTED_MIN}: "
        f"{r.trust_stats['share_below_trusted']:.1%}",
        "",
        "NOTE: diagnostic only. AttributionEngine is not evaluated on SWaT (D011-D); k is "
        "neutralised, not just unreported (D011-C). 'events flagged' = Attack_v0 onsets "
        "flagged at least once / onsets, from swat_eval.compute_latency.",
    ]
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--limit", type=int, default=None, help="row limit per file (fast iteration)"
    )
    args = parser.parse_args()
    print(format_report(run_ablation(args.data_dir, args.limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
