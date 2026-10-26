"""Fault-vs-attack attribution confusion matrix (O3), for simulated injections
and for labelled real bench captures.

Diagnostic/offline tooling: not production, not imported by ``edge/main.py``,
not on any acceptance path.

WHY: PRD O3 asks for ">= 85% attribution accuracy on labelled bench scenarios;
confusion matrix reported". No confusion matrix has existed until now. This
module produces one two ways:

  * ``synthetic`` -- the 8 hardware-free ``edge.injection`` types stamped onto
    ``simulator.generator.TelemetrySimulator`` streams, on EVERY channel, over
    several seeds. These numbers are SIMULATED. They measure the attribution
    logic's behaviour on synthetic Gaussian streams, never real-hardware
    accuracy.
  * ``bench`` -- a real ``edge/scripts/load_capture.py`` capture plus a small
    JSON labels file, so a real fault-injection session can be scored the day
    it is captured.

UNIT OF SCORING -- one labelled episode (one injection run, or one labelled
bench event) contributes ONE prediction: the attribution of the labelled
channel at the FIRST window, overlapping the episode, in which that channel is
flagged. Never flagged -> ``none`` (a missed detection, counted as wrong). This
mirrors the acceptance tests' "attribution at the flagging window" framing
(P2-ANOM-H2/H3). A window-level breakdown is reported alongside it.

CONTROL -- the same metric is computed on runs with NO injection, over the same
window span. At a ~10% clean per-window flag rate (measured on synthetic
streams, see BENCH_LOAD_VALIDATION.md section 9), a channel can be "flagged"
inside a 120-sample span by chance alone. The control row is the floor any
injection result must be read against.

STRUCTURAL CEILING (DECISIONS.md D014, reported, never hidden): the only
``PhysicsRule`` (``TrendSignPhysicsRule``, D013) can name ONLY ``current`` or
``vibration`` as an attack suspect. For temperature/pressure/humidity/gas an
``attack`` prediction is impossible by construction, so every attack injected
on those four channels is scored wrong. The report gives the all-channel
accuracy AND the current/vibration-only accuracy, and prints the ceiling.

Deployed configuration, matching ``edge/main.py`` / ``bench_if_tuning.py``:
IF threshold 0.90, identity filters, ``SeverityThresholdFlagPolicy()`` default,
``TrendSignPhysicsRule``, fit strictly on clean data before evaluation.

Injection magnitudes are EVALUATION FIXTURES expressed as multiples of each
channel's simulator noise SD, following ``test_p2_acceptance.py``'s own
conventions (spike 10x noise, ramp 0.5x noise/sample, constant spoof 5x
baseline, stealth cap 3x noise). They were fixed before running and never
tuned to improve a number.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline, WindowOutcome
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.eval.bench_fault_injection_eval import (
    DEFAULT_MAX_GAP_S,
    LIVE_THRESHOLD,
    _load_rows,
    _make_gas_gen,
)
from edge.injection.injections import (
    AdaptiveStealthFDI,
    BiasFDI,
    ConstantSpoof,
    Drift,
    Injection,
    RampFDI,
    Replay,
    Spike,
    StuckAt,
)
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider
from simulator.generator import BASELINES, TelemetrySimulator

PREDICTIONS = ("fault", "attack", "none")
PHYSICS_RULE_CHANNELS = frozenset({"current", "vibration"})  # D013/D014

# ---- synthetic-mode EVALUATION FIXTURES ------------------------------------
FIT_LEN = 600
ONSET = 120
DURATION = 120
TAIL = 60
STREAM_LEN = ONSET + DURATION + TAIL
DEFAULT_SEEDS = (1, 2, 3, 4, 5)
_FIT_SEED_OFFSET = 10_000  # fit stream never shares a seed with an eval stream


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class Episode:
    """One labelled episode and what the pipeline predicted for it."""

    group: str  # injection type name, or bench event name, or "control"
    channel: str
    truth: str  # "fault" | "attack" | "clean"
    predicted: str  # "fault" | "attack" | "none"
    window_counts: Counter = field(default_factory=Counter)  # over overlapping windows


def first_flag_prediction(outcomes: Sequence[WindowOutcome], channel: str) -> str:
    """Attribution of ``channel`` at the first window in which it is flagged,
    or ``"none"`` if it is never flagged in ``outcomes``."""
    for o in outcomes:
        if o.channel_flags[channel]:
            return o.attribution[channel].attribution.value
    return "none"


def window_counts(outcomes: Sequence[WindowOutcome], channel: str) -> Counter:
    """Per-window attribution of ``channel`` ('none' when unflagged)."""
    counts: Counter = Counter()
    for o in outcomes:
        counts[
            o.attribution[channel].attribution.value if o.channel_flags[channel] else "none"
        ] += 1
    return counts


@dataclass
class ConfusionReport:
    episodes: list[Episode]

    def matrix(self, predicate: Callable[[Episode], bool] = lambda e: True) -> dict:
        m: dict[str, Counter] = {}
        for e in self.episodes:
            if predicate(e):
                m.setdefault(e.truth, Counter())[e.predicted] += 1
        return m

    def accuracy(self, predicate: Callable[[Episode], bool] = lambda e: True) -> tuple[int, int]:
        scored = [e for e in self.episodes if predicate(e) and e.truth in ("fault", "attack")]
        return sum(1 for e in scored if e.predicted == e.truth), len(scored)


def format_matrix(m: dict, title: str) -> list[str]:
    header = "truth / predicted"
    lines = [title, f"  {header:<18}" + "".join(f"{p:>9}" for p in PREDICTIONS)]
    for truth in ("fault", "attack", "clean"):
        if truth in m:
            lines.append(f"  {truth:<18}" + "".join(f"{m[truth][p]:>9}" for p in PREDICTIONS))
    return lines


def _pct(num: int, den: int) -> str:
    return f"{num}/{den} ({num / den:.1%})" if den else "n/a"


# ---------------------------------------------------------------------------
# Pipeline construction (deployed configuration)
# ---------------------------------------------------------------------------


def _preprocessor() -> Preprocessor:
    return Preprocessor(median_kernel=1, low_pass_alpha=1.0)


@dataclass
class Fitted:
    detector: IsolationForestDetector
    flag_policy: SeverityThresholdFlagPolicy
    physics_rule: TrendSignPhysicsRule
    c_provider: ConsistencyProvider


def fit_components(fit_frames: list[TelemetryMessage]) -> Fitted:
    fit_windows = _preprocessor().process(fit_frames)
    if not fit_windows:
        raise ValueError("fit stream too short to form a single window")
    fitted = Fitted(
        detector=IsolationForestDetector(flag_threshold=LIVE_THRESHOLD, random_state=0),
        flag_policy=SeverityThresholdFlagPolicy(),
        physics_rule=TrendSignPhysicsRule(),
        c_provider=ConsistencyProvider(),
    )
    for target in (fitted.detector, fitted.flag_policy, fitted.physics_rule, fitted.c_provider):
        target.fit(fit_windows)
    return fitted


def build_pipeline(fitted: Fitted) -> P2Pipeline:
    """Fresh trust/k/h state; fitted components reused read-only."""
    return P2Pipeline(
        preprocessor=_preprocessor(),
        detector=fitted.detector,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(fitted.physics_rule),
        c_provider=fitted.c_provider,
        k_provider=CorrelationProvider(),
        h_provider=HReliabilityProvider(),
        flag_policy=fitted.flag_policy,
    )


# ---------------------------------------------------------------------------
# Synthetic mode
# ---------------------------------------------------------------------------


def _timestamps(n: int) -> list[str]:
    t0 = datetime(2026, 9, 24)
    return [(t0 + timedelta(seconds=i)).isoformat(timespec="milliseconds") + "Z" for i in range(n)]


def simulator_stream(n: int, seed: int) -> list[TelemetryMessage]:
    return TelemetrySimulator(seed=seed).generate(n, _timestamps(n))


def make_injection(name: str, channel: str) -> Injection:
    """The 8 injection types at their EVALUATION FIXTURE magnitudes."""
    mean, sd = BASELINES[channel]
    if name == "drift":
        return Drift(channel=channel, onset=ONSET, duration=DURATION, rate=0.5 * sd)
    if name == "spike":
        return Spike(channel=channel, onset=ONSET, duration=1, amplitude=10 * sd)
    if name == "stuck_at":
        return StuckAt(channel=channel, onset=ONSET, duration=DURATION)
    if name == "bias_fdi":
        return BiasFDI(channel=channel, onset=ONSET, duration=DURATION, bias=10 * sd)
    if name == "ramp_fdi":
        return RampFDI(channel=channel, onset=ONSET, duration=DURATION, slope=0.5 * sd)
    if name == "replay":
        return Replay(channel=channel, onset=ONSET, duration=DURATION, source_onset=0)
    if name == "constant_spoof":
        return ConstantSpoof(channel=channel, onset=ONSET, duration=DURATION, value=5 * mean)
    if name == "adaptive_stealth_fdi":
        cap = 3 * sd
        return AdaptiveStealthFDI(
            channel=channel, onset=ONSET, duration=DURATION, rate=cap / 10, residual_cap=cap
        )
    raise ValueError(f"unknown injection {name!r}")


INJECTION_NAMES = (
    "drift",
    "spike",
    "stuck_at",
    "bias_fdi",
    "ramp_fdi",
    "replay",
    "constant_spoof",
    "adaptive_stealth_fdi",
)


def _span_outcomes(outcomes: Sequence[WindowOutcome], lo: int, hi: int) -> list[WindowOutcome]:
    """Windows overlapping stream indices [lo, hi)."""
    return [o for o in outcomes if o.window.end_index > lo and o.window.start_index < hi]


def run_synthetic(seeds: Sequence[int] = DEFAULT_SEEDS) -> ConfusionReport:
    episodes: list[Episode] = []
    for seed in seeds:
        fitted = fit_components(simulator_stream(FIT_LEN, seed + _FIT_SEED_OFFSET))
        clean = simulator_stream(STREAM_LEN, seed)
        control = _span_outcomes(build_pipeline(fitted).process(clean), ONSET, ONSET + DURATION)

        for channel in CHANNELS:
            episodes.append(
                Episode(
                    group="control (no injection)",
                    channel=channel,
                    truth="clean",
                    predicted=first_flag_prediction(control, channel),
                    window_counts=window_counts(control, channel),
                )
            )
            for name in INJECTION_NAMES:
                injection = make_injection(name, channel)
                frames = injection.apply(clean).frames
                span = _span_outcomes(
                    build_pipeline(fitted).process(frames),
                    injection.onset,
                    injection.onset + injection.duration,
                )
                episodes.append(
                    Episode(
                        group=name,
                        channel=channel,
                        truth=injection.kind.value,
                        predicted=first_flag_prediction(span, channel),
                        window_counts=window_counts(span, channel),
                    )
                )
    return ConfusionReport(episodes)


# ---------------------------------------------------------------------------
# Bench mode
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchLabel:
    name: str
    t_start: float
    t_end: float
    channel: str | None
    cls: str  # "fault" | "attack" | "ignore"


def load_labels(path: str) -> list[BenchLabel]:
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    labels = []
    for item in raw["events"]:
        cls = item["class"]
        if cls not in ("fault", "attack", "ignore"):
            raise ValueError(f"label class must be fault/attack/ignore, got {cls!r}")
        channel = item.get("channel")
        if cls != "ignore" and channel not in CHANNELS:
            raise ValueError(f"label channel must be one of {CHANNELS}, got {channel!r}")
        labels.append(
            BenchLabel(
                name=item["name"],
                t_start=float(item["t_start"]),
                t_end=float(item["t_end"]),
                channel=channel,
                cls=cls,
            )
        )
    return labels


def bench_segments(
    rows: list[dict], max_gap_s: float
) -> tuple[list[list[TelemetryMessage]], Callable[[str], float]]:
    """Build Sampler-equivalent frames (all-five-healthy rows only, ``gas``
    from the deployed fake generator) and split them at real time gaps --
    the same discipline as ``bench_fault_injection_eval.py``, whose segmentation
    lives inline in its ``main()`` and so cannot be imported directly."""
    t0 = datetime.fromisoformat(rows[0]["ts"].replace("Z", "+00:00"))

    def rel_t(ts: str) -> float:
        return (datetime.fromisoformat(ts.replace("Z", "+00:00")) - t0).total_seconds()

    gas_gen = _make_gas_gen()
    messages: list[TelemetryMessage] = []
    for row in rows:
        if not all(
            row[k]
            for k in (
                "temperature_healthy",
                "humidity_healthy",
                "pressure_healthy",
                "current_healthy",
                "vibration_healthy",
            )
        ):
            continue
        messages.append(
            TelemetryMessage(
                device_id="pump-01",
                ts=row["ts"],
                sensors={
                    "temperature": row["temperature_c"],
                    "vibration": row["vibration_g_driver"],
                    "pressure": row["pressure_hpa"],
                    "humidity": row["humidity_pct"],
                    "gas": gas_gen(),
                    "current": row["current_a"],
                },
                sample_seq=len(messages),
            )
        )
    if not messages:
        raise ValueError("no fully-healthy frames in capture")

    segments: list[list[TelemetryMessage]] = []
    current: list[TelemetryMessage] = [messages[0]]
    for prev, msg in zip(messages, messages[1:], strict=False):
        if rel_t(msg.ts) - rel_t(prev.ts) > max_gap_s:
            segments.append(current)
            current = []
        current.append(msg)
    segments.append(current)
    return segments, rel_t


@dataclass
class BenchResult:
    report: ConfusionReport
    control_counts: dict[str, Counter]  # per channel, over unlabelled windows
    n_windows: int
    segments: list[tuple[float, float, int]]


def run_bench(capture: str, labels_path: str, max_gap_s: float = DEFAULT_MAX_GAP_S) -> BenchResult:
    rows = _load_rows(capture)
    labels = load_labels(labels_path)
    segments, rel_t = bench_segments(rows, max_gap_s)

    fit_segment = segments[0]
    fitted = fit_components(fit_segment)
    first_label_t = min(lb.t_start for lb in labels)
    if rel_t(fit_segment[-1].ts) >= first_label_t:
        print(
            "WARNING: the fit segment overlaps the first labelled event; fit is "
            "not strictly clean -- results are optimistic.",
            file=sys.stderr,
        )

    pipeline = build_pipeline(fitted)
    timed: list[tuple[float, float, WindowOutcome]] = []
    window_size = _preprocessor().window_size
    for seg in segments:
        if len(seg) < window_size:
            continue
        for o in pipeline.process(seg):
            timed.append(
                (rel_t(seg[o.window.start_index].ts), rel_t(seg[o.window.end_index - 1].ts), o)
            )

    def overlapping(lo: float, hi: float) -> list[WindowOutcome]:
        return [o for (ts, te, o) in timed if te >= lo and ts <= hi]

    episodes = []
    for lb in labels:
        if lb.cls == "ignore":
            continue
        span = overlapping(lb.t_start, lb.t_end)
        episodes.append(
            Episode(
                group=lb.name,
                channel=lb.channel,
                truth=lb.cls,
                predicted=first_flag_prediction(span, lb.channel),
                window_counts=window_counts(span, lb.channel),
            )
        )

    unlabelled = [
        o for (ts, te, o) in timed if not any(te >= lb.t_start and ts <= lb.t_end for lb in labels)
    ]
    control = {ch: window_counts(unlabelled, ch) for ch in CHANNELS}
    seg_info = [(rel_t(s[0].ts), rel_t(s[-1].ts), len(s)) for s in segments]
    return BenchResult(ConfusionReport(episodes), control, len(timed), seg_info)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def format_synthetic(report: ConfusionReport, seeds: Sequence[int]) -> str:
    lines = [
        "=== O3 attribution confusion matrix -- SIMULATED (not a real-hardware claim) ===",
        f"streams: simulator.TelemetrySimulator, seeds={list(seeds)}, onset={ONSET}, "
        f"duration={DURATION} (spike: 1 sample), IF threshold={LIVE_THRESHOLD}",
        "",
        "-- HEADLINE: window-level matrix (every window overlapping an episode) --",
        "  rows = truth of the window's labelled channel, columns = its attribution",
    ]
    for label, pred in (
        ("all 6 channels", lambda e: True),
        ("current + vibration only", lambda e: e.channel in PHYSICS_RULE_CHANNELS),
        ("temperature/pressure/humidity/gas", lambda e: e.channel not in PHYSICS_RULE_CHANNELS),
    ):
        lines.append(f"  [{label}]")
        for truth in ("clean", "fault", "attack"):
            wc: Counter = Counter()
            for e in report.episodes:
                if e.truth == truth and pred(e):
                    wc.update(e.window_counts)
            total = sum(wc.values())
            if total:
                lines.append(
                    f"    truth={truth:<7} windows={total:>6}  "
                    + "  ".join(f"{p}={wc[p] / total:.1%}" for p in PREDICTIONS)
                )
    lines += [
        "",
        "-- SECONDARY: episode-level (first-flag attribution of the injected channel) --",
        "  CONFOUNDED: the no-injection control is flagged by chance in almost every",
        "  120-sample span, so a 'fault' first-flag is NOT evidence the fault was seen.",
        "",
    ]
    lines += format_matrix(report.matrix(), "-- all 6 channels --")
    ok, n = report.accuracy()
    lines.append(f"  accuracy (fault+attack episodes): {_pct(ok, n)}")
    lines.append("")
    paired = lambda e: e.channel in PHYSICS_RULE_CHANNELS  # noqa: E731
    lines += format_matrix(report.matrix(paired), "-- current + vibration only --")
    ok, n = report.accuracy(paired)
    lines.append(f"  accuracy (fault+attack episodes): {_pct(ok, n)}")
    lines.append("")
    unpaired = lambda e: e.channel not in PHYSICS_RULE_CHANNELS  # noqa: E731
    lines += format_matrix(
        report.matrix(unpaired), "-- temperature/pressure/humidity/gas (D014) --"
    )
    ok, n = report.accuracy(unpaired)
    lines.append(f"  accuracy (fault+attack episodes): {_pct(ok, n)}")
    attack_unpaired = [e for e in report.episodes if unpaired(e) and e.truth == "attack"]
    lines.append(
        "  D014 STRUCTURAL CEILING: 'attack' can never be predicted on these 4 "
        f"channels -> {len(attack_unpaired)} attack episodes are wrong by construction."
    )
    lines.append("")
    lines.append("-- per injection type (all channels) --")
    lines.append(f"  {'type':<24}{'truth':>7}{'fault':>7}{'attack':>8}{'none':>6}{'acc':>9}")
    for name in ("control (no injection)", *INJECTION_NAMES):
        eps = [e for e in report.episodes if e.group == name]
        c = Counter(e.predicted for e in eps)
        truth = eps[0].truth if eps else "-"
        correct = sum(1 for e in eps if e.predicted == e.truth)
        acc = f"{correct / len(eps):.0%}" if truth != "clean" and eps else "-"
        lines.append(f"  {name:<24}{truth:>7}{c['fault']:>7}{c['attack']:>8}{c['none']:>6}{acc:>9}")
    return "\n".join(lines)


def format_bench(result: BenchResult) -> str:
    lines = ["=== O3 attribution -- REAL BENCH capture ===", "segments (t_start, t_end, n):"]
    lines += [f"  {a:>7.1f}s -> {b:>7.1f}s  n={n}" for a, b, n in result.segments]
    lines.append(f"windows evaluated: {result.n_windows}")
    lines.append("")
    lines.append(f"  {'event':<34}{'channel':<11}{'truth':<8}{'predicted':<10}window counts")
    for e in result.report.episodes:
        wc = ", ".join(f"{p}={e.window_counts[p]}" for p in PREDICTIONS)
        lines.append(f"  {e.group:<34}{e.channel:<11}{e.truth:<8}{e.predicted:<10}{wc}")
    ok, n = result.report.accuracy()
    lines.append(f"  episode accuracy: {_pct(ok, n)}")
    lines.append("")
    lines.append("-- unlabelled windows (false-alarm control, per channel) --")
    for ch in CHANNELS:
        c = result.control_counts[ch]
        total = sum(c.values())
        lines.append(
            f"  {ch:<12} windows={total:>4}  flagged-fault={c['fault']:>4}  "
            f"flagged-attack={c['attack']:>4}"
        )
    lines.append("")
    lines.append(
        "NOTE: n is tiny (one capture). This is a scored example, not an accuracy "
        "estimate. D014: only current/vibration can ever be predicted 'attack'."
    )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    syn = sub.add_parser("synthetic", help="simulated injections on every channel")
    syn.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    bench = sub.add_parser("bench", help="a real load_capture.py capture + labels JSON")
    bench.add_argument("capture")
    bench.add_argument("labels")
    bench.add_argument("--max-gap-s", type=float, default=DEFAULT_MAX_GAP_S)
    args = parser.parse_args()

    if args.mode == "synthetic":
        print(format_synthetic(run_synthetic(args.seeds), args.seeds))
    else:
        print(format_bench(run_bench(args.capture, args.labels, args.max_gap_s)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
