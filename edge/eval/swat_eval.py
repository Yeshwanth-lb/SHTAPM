"""SWaT.A1 evaluation harness (hardware-free, DIAGNOSTIC — NOT P2 acceptance).

Implements the D011-frozen validation methodology using the D012-locked
six-tag mapping, over the real ``SWaT_Dataset_Normal_v1.xlsx`` /
``SWaT_Dataset_Attack_v0.xlsx`` files (not redistributed; expected under a
local, gitignored ``datasets/`` directory).

D012 mapping (plumbing/proxy substitution ONLY — see DECISIONS.md D011/D012.
NO claim of physical equivalence to any bench channel is made or implied
anywhere in this module. In particular ``AIT402`` is aqueous
Oxidation-Reduction-Potential of the RO feed water, NOT an ambient-gas
reading, and must never be described as one)::

    temperature <- LIT101
    vibration   <- AIT203
    pressure    <- DPIT301
    humidity    <- LIT401
    gas         <- AIT402   (aqueous ORP; proxy slot only)
    current     <- PIT501

Statefulness (why this is NOT two independent per-file runs):
    ``Preprocessor`` windowing/min-max normalization is stateless per window,
    but ``HReliabilityProvider`` (h) and ``TrustEngine``'s ``BetaState`` carry
    real memory across windows, and ``IsolationForestDetector``/
    ``ConsistencyProvider`` must be fit ONCE on ``Normal_v1``-only windows and
    that SAME fitted instance reused for scoring. This harness therefore:
      1. Builds ``Normal_v1``-only windows via a dedicated ``Preprocessor.process()``
         call and fits IF + ``c`` on those windows ONLY (D011 F: no fitting may
         touch ``Attack_v0``).
      2. Runs ONE continuous ``P2Pipeline.process()`` call over
         ``Normal_v1`` frames immediately followed by ``Attack_v0`` frames (their
         real, contiguous timestamps), so h/k/trust state warms up naturally
         across the clean period before the labeled-attack period begins.
      3. Reports metrics ONLY for windows whose window is fully inside the
         ``Attack_v0`` region (``start_index >= len(normal_frames)``) — the
         warm-up windows are processed but not scored.

Explicitly excluded from every report (D011 C/D — not a "not yet validated"
omission, a hard exclusion):
    - ``k`` (CorrelationProvider) runs mechanically (required by
      ``TrustEngine``) but its value is NEVER read or reported — current and
      vibration are confirmed absent from SWaT (D010), so `k`'s output here is
      physically meaningless.
    - ``AttributionEngine`` runs against a null ``PhysicsRule`` stub (required
      by its constructor) but its output is NEVER read or reported —
      no concrete ``PhysicsRule`` exists (D011 D); no O3 claim is made.

EVALUATION FIXTURES ONLY (labelled, NOT project specifications; see
``edge/eval/if_eval.py`` for the same discipline):
    - ``FLAG_THRESHOLD_FIXTURE`` — IF hyperparameter tuning is a separate,
      later step (P2_RESUME.md §7 step 2); this value only lets the harness
      report numbers today.
    - ``WINDOW_SIZE`` / ``STEP`` — non-overlapping windows (step == window
      size), chosen for tractable runtime over ~945k combined rows and to
      avoid pseudo-replicated, heavily-autocorrelated samples in the reported
      rates.
    - ``MEDIAN_KERNEL`` / ``LOW_PASS_ALPHA`` — identity smoothing (same
      fixture convention as ``if_eval.py``/``preproc_experiment.py``).
    - ``IF_RANDOM_STATE`` — determinism only.
    - Normalization choice (per-window min-max, current production behaviour)
      is NOT revisited here — that is a separate, later step
      (P2_RESUME.md §7 step 3).

No production code is imported and modified: everything below is composed
from the existing, unmodified P2 components. The frozen telemetry contract
is used exactly as-is via the shared ``build_telemetry`` builder.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.attribution import AttributionEngine, PhysicsCheck
from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor, Window
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

# ---- EVALUATION FIXTURES ONLY (see module docstring) ------------------------
DEVICE_ID = "swat-a1-eval"
MEDIAN_KERNEL = 1  # identity (no undocumented smoothing) — same as if_eval.py
LOW_PASS_ALPHA = 1.0  # identity — same as if_eval.py
WINDOW_SIZE = 30  # documented default (Doc05 thresholds)
STEP = WINDOW_SIZE  # non-overlapping: tractable runtime + avoids pseudo-replication
FLAG_THRESHOLD_FIXTURE = 0.95  # eval-only; NOT a project threshold (matches if_eval.py)
IF_RANDOM_STATE = 0  # determinism only
VARIANCE_FACTOR_FIXTURE = 0.5  # ChannelFlagPolicy default; untuned (U07-gated)

# D012 — frozen six-tag plumbing/proxy mapping. Single source of truth; do not
# duplicate this mapping elsewhere. See DECISIONS.md D012 for the evidence.
TAG_MAP: dict[str, str] = {
    "temperature": "LIT101",
    "vibration": "AIT203",
    "pressure": "DPIT301",
    "humidity": "LIT401",
    "gas": "AIT402",  # aqueous ORP — proxy slot ONLY, not an ambient-gas reading
    "current": "PIT501",
}
SOURCE_TAGS = list(TAG_MAP.values())

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "datasets"
NORMAL_FILENAME = "SWaT_Dataset_Normal_v1.xlsx"
ATTACK_FILENAME = "SWaT_Dataset_Attack_v0.xlsx"


# ------------------------------------------------------------------
# Label normalization (fixes the confirmed "A ttack" typo in Attack_v0)
# ------------------------------------------------------------------


def normalize_label(raw: str) -> str:
    """Normalize a raw SWaT ``Normal/Attack`` label.

    Confirmed data-quality issue (DECISIONS.md D012): 37 rows in the official
    ``Attack_v0`` file carry the label ``"A ttack"`` (an embedded space) instead
    of ``"Attack"``. Stripping ALL whitespace (not just leading/trailing) before
    comparison merges these correctly; verified against the actual file this
    yields exactly {"Normal", "Attack"} with counts matching the full row count.
    """
    cleaned = "".join(raw.split())
    if cleaned not in ("Normal", "Attack"):
        raise ValueError(f"unrecognized SWaT label {raw!r} (normalized to {cleaned!r})")
    return cleaned


def swat_timestamp_to_iso(raw: str) -> str:
    """Convert a SWaT ``' DD/MM/YYYY H:MM:SS AM/PM'`` timestamp to the frozen
    contract's ISO-8601-with-ms string format (FR-Q2)."""
    dt = datetime.strptime(raw.strip(), "%d/%m/%Y %I:%M:%S %p")
    return dt.isoformat(timespec="milliseconds") + "Z"


# ------------------------------------------------------------------
# Null PhysicsRule stub — AttributionEngine's constructor requires a rule;
# D011 D blocks any real rule from existing. This stub's output is NEVER read.
# ------------------------------------------------------------------


class _NullPhysicsRule:
    """Never reports a violation. Required only to satisfy AttributionEngine's
    constructor; its output is excluded from every report (D011 D)."""

    def check(self, window: Window) -> PhysicsCheck:
        return PhysicsCheck(violated=False, suspect_channel=None, reason="")


# ------------------------------------------------------------------
# Loading + D012 relabeling
# ------------------------------------------------------------------


@dataclass
class SwatFile:
    frames: list[TelemetryMessage]
    labels: list[str]  # normalized "Normal"/"Attack", kept OUTSIDE TelemetryMessage


def _find_header_row(ws, wanted: set[str]) -> tuple[int, dict[str, int]]:
    """Scan for the real per-tag header row (SWaT sheets have a blank or
    process-group-label row before it) and return (row_number, name->col_index)."""
    for row in ws.iter_rows(min_row=1, max_row=5):
        names = {str(c.value).strip(): idx for idx, c in enumerate(row) if c.value is not None}
        if wanted.issubset(names.keys()):
            return row[0].row, names
    raise ValueError(f"could not locate a header row containing {wanted}")


def load_swat_file(path: Path, sheet_name: str, limit: int | None = None) -> SwatFile:
    """Load one SWaT .xlsx file, relabel D012's six source tags onto the frozen
    channel names, and return frames + a separate (not-in-contract) label list.

    Only the six D012 source tags + Timestamp + Normal/Attack are read (not all
    51 tags) — everything the pipeline needs, nothing it doesn't.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet_name]
    wanted = {"Timestamp", "Normal/Attack", *SOURCE_TAGS}
    header_row, col_of = _find_header_row(ws, wanted)

    ts_col = col_of["Timestamp"]
    label_col = col_of["Normal/Attack"]
    tag_cols = {ch: col_of[tag] for ch, tag in TAG_MAP.items()}

    frames: list[TelemetryMessage] = []
    labels: list[str] = []
    seq = 0
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if row is None or all(v is None for v in row):
            continue
        ts_iso = swat_timestamp_to_iso(str(row[ts_col]))
        sensors = {ch: float(row[c]) for ch, c in tag_cols.items()}
        frames.append(build_telemetry(DEVICE_ID, ts_iso, sensors, seq))
        labels.append(normalize_label(str(row[label_col])))
        seq += 1
        if limit is not None and seq >= limit:
            break
    wb.close()
    return SwatFile(frames=frames, labels=labels)


# ------------------------------------------------------------------
# Pipeline construction
# ------------------------------------------------------------------


def _preprocessor() -> Preprocessor:
    return Preprocessor(
        median_kernel=MEDIAN_KERNEL,
        low_pass_alpha=LOW_PASS_ALPHA,
        window_size=WINDOW_SIZE,
        step=STEP,
    )


def fit_baseline(
    normal_frames: list[TelemetryMessage],
) -> tuple[IsolationForestDetector, ConsistencyProvider]:
    """Fit IF + c on Normal_v1-only windows. D011 F: no Attack_v0 data here."""
    fit_windows = _preprocessor().process(normal_frames)
    detector = IsolationForestDetector(
        flag_threshold=FLAG_THRESHOLD_FIXTURE, random_state=IF_RANDOM_STATE
    )
    detector.fit(fit_windows)
    c_provider = ConsistencyProvider()
    c_provider.fit(fit_windows)
    return detector, c_provider


def build_pipeline(
    detector: IsolationForestDetector, c_provider: ConsistencyProvider
) -> P2Pipeline:
    return P2Pipeline(
        preprocessor=_preprocessor(),
        detector=detector,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(_NullPhysicsRule()),
        c_provider=c_provider,
        k_provider=CorrelationProvider(),  # runs mechanically; NEVER reported (D011 C)
        h_provider=HReliabilityProvider(),
        flag_policy=SeverityThresholdFlagPolicy(variance_factor=VARIANCE_FACTOR_FIXTURE),
    )


# ------------------------------------------------------------------
# Report
# ------------------------------------------------------------------


@dataclass
class ConfusionMatrix:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def fp_rate(self) -> float:
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else 0.0

    @property
    def detection_rate(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0


def attack_onsets(labels: list[str], start: int) -> list[int]:
    """Row-indices (>= ``start``) where a contiguous run of ``"Attack"``-labeled
    rows begins: the label at ``i`` is ``"Attack"`` and either ``i == start`` or
    the previous row's label is not ``"Attack"``. Operates on already-normalized
    labels (see ``normalize_label``); does not invent or infer any onset beyond
    what the dataset's own per-row labels state."""
    onsets: list[int] = []
    for i in range(start, len(labels)):
        if labels[i] == "Attack" and (i == start or labels[i - 1] != "Attack"):
            onsets.append(i)
    return onsets


@dataclass
class LatencyReport:
    """Detection latency, in units of (non-overlapping) evaluation windows,
    from each contiguous Attack-labeled onset to the first flagged evaluation
    window at or after that onset.

    latency = 1 means the window that first covers the onset row was itself
    flagged (immediate detection); latency = 3 means it took three windows
    from onset. This mirrors the project's own "flagged <= 3 windows" framing
    (P2-ANOM-H2/H3) but is NOT a claim that any such acceptance criterion is
    met here — see the module/format_report disclaimers.

    Two failure buckets are tracked SEPARATELY and are NEVER folded into the
    latency statistics:
      - ``n_not_evaluable``: the onset row is not covered by any produced
        evaluation window (only possible with a trailing partial window,
        e.g. under --limit; does not occur in a full, unlimited run since
        495000 rows / 30-row windows divides evenly).
      - ``n_never_flagged``: the onset IS covered by evaluation windows, but
        none of them, from the covering window through the end of the
        evaluation region, was ever flagged. This is an honest miss, not an
        infinite or undefined latency, and must be reported as its own count
        — never averaged in, never silently dropped.
    """

    n_onsets: int
    n_not_evaluable: int
    n_never_flagged: int
    latencies_windows: list[int] = field(default_factory=list)

    @property
    def n_flagged(self) -> int:
        return len(self.latencies_windows)

    @property
    def mean_latency_windows(self) -> float | None:
        return statistics.fmean(self.latencies_windows) if self.latencies_windows else None

    @property
    def median_latency_windows(self) -> float | None:
        return statistics.median(self.latencies_windows) if self.latencies_windows else None

    @property
    def max_latency_windows(self) -> int | None:
        return max(self.latencies_windows) if self.latencies_windows else None


def compute_latency(
    eval_outcomes: list,
    combined_labels: list[str],
    eval_boundary: int,
) -> LatencyReport:
    """Compute :class:`LatencyReport` from an ORDERED list of eval-region
    ``WindowOutcome``s (i.e. ``outcome.window.start_index >= eval_boundary``
    for all of them, already sorted by ``start_index``, no gaps between
    consecutive windows). Requires non-overlapping windows (``STEP ==
    WINDOW_SIZE``) so a row index maps to exactly one window by floor
    division — asserted below rather than silently assumed.

    Each onset's search for a flagged window is bounded to END BEFORE the
    NEXT onset's covering window (or the end of the eval region, for the
    last onset). Without this bound, a later and entirely unrelated attack's
    flag could be misattributed as a delayed detection of an earlier attack
    that was, in truth, never flagged at all — this was caught by this
    module's own tests during development and is deliberately guarded
    against, not an oversight."""
    assert STEP == WINDOW_SIZE, "compute_latency assumes non-overlapping evaluation windows"

    onsets = attack_onsets(combined_labels, eval_boundary)
    onset_window_indices = [(o - eval_boundary) // WINDOW_SIZE for o in onsets]
    n_not_evaluable = 0
    n_never_flagged = 0
    latencies: list[int] = []

    for k, i in enumerate(onset_window_indices):
        if i >= len(eval_outcomes):
            n_not_evaluable += 1  # onset falls in a trailing partial window (e.g. --limit)
            continue
        upper = (
            onset_window_indices[k + 1] if k + 1 < len(onset_window_indices) else len(eval_outcomes)
        )
        upper = min(upper, len(eval_outcomes))
        flagged_at = None
        for j in range(i, upper):
            if eval_outcomes[j].anomaly.flag:
                flagged_at = j
                break
        if flagged_at is None:
            n_never_flagged += 1  # covered, but never flagged — an honest miss
        else:
            latencies.append(flagged_at - i + 1)

    return LatencyReport(
        n_onsets=len(onsets),
        n_not_evaluable=n_not_evaluable,
        n_never_flagged=n_never_flagged,
        latencies_windows=latencies,
    )


@dataclass
class SwatEvalReport:
    n_fit_windows: int
    n_eval_windows: int
    n_eval_windows_normal: int
    n_eval_windows_attack: int
    confusion: ConfusionMatrix
    latency: LatencyReport
    c_mean_normal: dict[str, float]
    c_mean_attack: dict[str, float]
    h_mean_normal: dict[str, float]
    h_mean_attack: dict[str, float]


def run_eval(data_dir: Path = DEFAULT_DATA_DIR, limit: int | None = None) -> SwatEvalReport:
    """Deterministic end-to-end run. NOT a P2 acceptance result — see module
    docstring for what is and is not reported."""
    normal = load_swat_file(data_dir / NORMAL_FILENAME, "Normal.csv", limit=limit)
    attack = load_swat_file(data_dir / ATTACK_FILENAME, "Combined Data", limit=limit)

    detector, c_provider = fit_baseline(normal.frames)
    fit_window_count = len(_preprocessor().process(normal.frames))

    pipeline = build_pipeline(detector, c_provider)
    combined_frames = normal.frames + attack.frames
    combined_labels = normal.labels + attack.labels
    eval_boundary = len(normal.frames)

    outcomes = pipeline.process(combined_frames)
    # Ordered (pipeline.process preserves window order), eval-region-only subset —
    # shared by the confusion matrix below and by compute_latency().
    eval_outcomes = [o for o in outcomes if o.window.start_index >= eval_boundary]

    confusion = ConfusionMatrix()
    c_normal: dict[str, list[float]] = {ch: [] for ch in CHANNELS}
    c_attack: dict[str, list[float]] = {ch: [] for ch in CHANNELS}
    h_normal: dict[str, list[float]] = {ch: [] for ch in CHANNELS}
    h_attack: dict[str, list[float]] = {ch: [] for ch in CHANNELS}
    n_eval = n_eval_normal = n_eval_attack = 0

    for outcome in eval_outcomes:
        w = outcome.window
        n_eval += 1
        window_labels = combined_labels[w.start_index : w.end_index]
        is_attack_window = "Attack" in window_labels
        flagged = outcome.anomaly.flag
        if is_attack_window:
            n_eval_attack += 1
            if flagged:
                confusion.tp += 1
            else:
                confusion.fn += 1
        else:
            n_eval_normal += 1
            if flagged:
                confusion.fp += 1
            else:
                confusion.tn += 1

        bucket_c = c_attack if is_attack_window else c_normal
        bucket_h = h_attack if is_attack_window else h_normal
        for ch in CHANNELS:
            bucket_c[ch].append(outcome.trust[ch].g)  # descriptive only; g, not raw c
            bucket_h[ch].append(outcome.trust[ch].trust)

    def _mean(d: dict[str, list[float]]) -> dict[str, float]:
        return {ch: (statistics.fmean(v) if v else float("nan")) for ch, v in d.items()}

    latency = compute_latency(eval_outcomes, combined_labels, eval_boundary)

    return SwatEvalReport(
        n_fit_windows=fit_window_count,
        n_eval_windows=n_eval,
        n_eval_windows_normal=n_eval_normal,
        n_eval_windows_attack=n_eval_attack,
        confusion=confusion,
        latency=latency,
        c_mean_normal=_mean(c_normal),
        c_mean_attack=_mean(c_attack),
        h_mean_normal=_mean(h_normal),
        h_mean_attack=_mean(h_attack),
    )


def format_report(r: SwatEvalReport) -> str:
    lines: list[str] = []
    lines.append("=== SWaT.A1 P2 evaluation harness (DIAGNOSTIC, NOT P2 acceptance) ===")
    lines.append(
        f"FIXTURES: window={WINDOW_SIZE} step={STEP} threshold(EVAL)={FLAG_THRESHOLD_FIXTURE} "
        f"if_random_state={IF_RANDOM_STATE} variance_factor={VARIANCE_FACTOR_FIXTURE}"
    )
    lines.append(f"D012 mapping: {TAG_MAP}")
    lines.append("")
    lines.append(f"Fit windows (Normal_v1 only): {r.n_fit_windows}")
    lines.append(
        f"Eval windows (Attack_v0 only, fully post-boundary): {r.n_eval_windows} "
        f"(normal-labeled={r.n_eval_windows_normal}, attack-labeled={r.n_eval_windows_attack})"
    )
    lines.append("")
    lines.append("-- O10-style confusion matrix (window-level, EVALUATION FIXTURE threshold) --")
    lines.append(
        f"TP={r.confusion.tp} FP={r.confusion.fp} TN={r.confusion.tn} FN={r.confusion.fn} "
        f"fp_rate={r.confusion.fp_rate:.3f} detection_rate={r.confusion.detection_rate:.3f}"
    )
    lines.append("")
    lines.append(
        "-- Detection latency (windows from each Attack onset to first flagged "
        "window at/after it; latency=1 is immediate) --"
    )
    lat = r.latency
    mean_s = "n/a" if lat.mean_latency_windows is None else f"{lat.mean_latency_windows:.2f}"
    median_s = "n/a" if lat.median_latency_windows is None else f"{lat.median_latency_windows:.2f}"
    max_s = "n/a" if lat.max_latency_windows is None else str(lat.max_latency_windows)
    lines.append(
        f"onsets={lat.n_onsets} flagged={lat.n_flagged} never_flagged={lat.n_never_flagged} "
        f"not_evaluable={lat.n_not_evaluable}"
    )
    lines.append(
        f"latency_windows[mean/median/max over FLAGGED onsets only]={mean_s}/{median_s}/{max_s}"
    )
    lines.append("")
    lines.append("-- c/h descriptive trajectory (mean g / mean trust, by window label) --")
    lines.append("channel      g(normal) g(attack)  trust(normal) trust(attack)")
    for ch in CHANNELS:
        lines.append(
            f"{ch:12s} {r.c_mean_normal[ch]:9.3f} {r.c_mean_attack[ch]:9.3f}  "
            f"{r.h_mean_normal[ch]:12.3f} {r.h_mean_attack[ch]:13.3f}"
        )
    lines.append("")
    lines.append(
        "NOTE: this is a DIAGNOSTIC report, NOT a P2 acceptance result. `k` and "
        "`AttributionEngine`/O3 are excluded entirely per D011 C/D (k is physically "
        "meaningless on SWaT; no PhysicsRule exists). The D012 mapping is a "
        "plumbing/proxy substitution ONLY — no physical equivalence to any bench "
        "channel is claimed. `gas` here is aqueous ORP (AIT402), never an "
        "ambient-gas reading. IF threshold/hyperparameters and the normalization "
        "choice remain UNTUNED and dataset-gated — see P2_RESUME.md §7."
    )
    return "\n".join(lines)


def main() -> None:
    # Some Windows consoles default stdout to a non-UTF-8 codepage, which
    # raises/garbles on the report's em-dashes and section marks. Reconfigure
    # defensively; this only affects how output is ENCODED for display, not
    # any evaluation logic or report content.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="directory containing the SWaT .xlsx files",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="row limit per file, for fast local iteration only"
    )
    args = parser.parse_args()
    print(format_report(run_eval(data_dir=args.data_dir, limit=args.limit)))


if __name__ == "__main__":
    main()
