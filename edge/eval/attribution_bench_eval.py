"""Fault-vs-attack attribution on REAL bench streams: TrendSign vs OperatingState.

Diagnostic/offline tooling: not production, not imported by ``edge/main.py``.

WHY. ``attribution_confusion.py`` injects into the simulator, whose channels are
independent Gaussians with no physics: it cannot exercise a rule that reasons
about cross-sensor physics at all. This harness injects the same
``edge.injection`` types into REAL bench captures, where current and vibration
genuinely co-vary with the motor, and runs the exact live P2 composition
(identity preprocessing, Isolation Forest at the deployed 0.90 threshold,
SeverityThresholdFlagPolicy, c/k/h with the D033 gate) with only the physics
rule swapped. Same episodes, same scoring, both rules.

STREAMS (frozen-contract frames; load-capture rows are converted, ``gas`` is
filled with the same realistic fake generator the live service uses):
  * idle     -- ``telemetry_capture_5sensor_nominal.jsonl`` (7.2 h, motor off)
  * cycling  -- ``motor_load_full.jsonl`` (19 min, four motor ON/OFF cycles)

EPISODES. For each stream: fit every calibrated component on the first
``--fit-fraction`` of the stream, then inject one scenario at a time at onsets
spread over the remainder, each into an otherwise untouched copy. Magnitudes
are evaluation fixtures, chosen per stream state at the onset:
  * attacks that CROSS the motor state (spoof/bias/replay towards the other
    state: fake a running motor while idle, hide a running one) -- the
    physically detectable case;
  * attacks that STAY in state (spoof at the true median, small bias, stealth
    FDI) -- physically consistent by construction, reported separately so the
    rule's limit is visible rather than averaged away;
  * faults: short spike (2 samples), stuck-at (holds the onset value), drift.
Drift and ramp injection are the same waveform; both are run, and the result
shows what physics can and cannot tell apart.

SCORING per episode on the injected channel: ``detected`` = flagged in any
window overlapping the injection; ``first`` = attribution at the first flagged
window; ``settled`` = majority attribution over all flagged windows. Clean
control: per-window attack/fault labels on the uninjected eval segment.

Run (repo root):
    PYTHONPATH="backend;." python -m edge.eval.attribution_bench_eval
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from app.schemas.build import build_telemetry
from app.schemas.contracts import TelemetryMessage

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.operating_state_rule import (
    BENCH_CURRENT_BANDS,
    BENCH_VIBRATION_BANDS,
    RUNNING,
    OperatingStateRule,
    StateBands,
    calibrate_vibration_bands,
)
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.drivers.fake import realistic_raw
from edge.injection import (
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
from edge.models.p2_baseline import parse_capture, split_segments
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import BENCH_RUNNING_GATE, CorrelationProvider
from edge.trust.k_operating_state import OperatingStateCorrelationProvider

WINDOW = 30
DETECTOR_THRESHOLD = 0.90  # edge/main.py's live value
WARMUP = 120  # clean frames before each onset so trust starts settled
TAIL = 60  # frames after the injection, to catch late flags
DURATION = 60
SPACING = 240
CLEAN_CONTROL_FRAMES = 2400  # ~40 min at the bench's ~1 frame/s


# name -> (rule factory, physics_flags). The third variant lets a physics
# violation flag its suspect channel even when the statistical policy is silent.
@dataclass(frozen=True)
class Variant:
    rule: str  # "trend_sign" | "op_state"
    physics_flags: bool
    calibrated: bool = False  # D036: vibration bands learned from the fit data
    operating_state_k: bool = False  # D035: k from motor-state consistency


RULES: dict[str, Variant] = {
    "trend_sign (D013)": Variant("trend_sign", physics_flags=False),
    "op_state": Variant("op_state", physics_flags=False),
    "op_state+physflags": Variant("op_state", physics_flags=True),
    "deployed (D034-36)": Variant(
        "op_state", physics_flags=True, calibrated=True, operating_state_k=True
    ),
}


# ---- streams ------------------------------------------------------------------


def _gas_source():
    return realistic_raw(baseline=150.0, noise_std=2.0, drift_std=0.5, seed=1_000_005)


def load_stream(path: Path) -> list[TelemetryMessage]:
    """Frozen-contract capture, or a ``load_capture.py`` capture converted."""
    first = path.open(encoding="utf-8").readline()
    if '"sensors"' in first:
        parsed = parse_capture(path.open(encoding="utf-8"))
        return [m for seg in split_segments(parsed.messages) for m in seg]
    gas = _gas_source()
    frames: list[TelemetryMessage] = []
    last_dht: tuple[float, float] | None = None
    for i, line in enumerate(path.open(encoding="utf-8")):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not all(row.get(f"{k}_healthy") for k in ("current", "vibration", "pressure")):
            continue
        # The DHT22 drops out under motor EMI (BENCH_LOAD_VALIDATION.md §4).
        # Attribution here reads only current and vibration, so a dropped
        # temperature/humidity sample carries the last healthy reading forward
        # instead of discarding the whole row -- otherwise most motor-running
        # rows would be lost. Rows before the first healthy DHT22 read are skipped.
        if row.get("temperature_healthy") and row.get("humidity_healthy"):
            last_dht = (row["temperature_c"], row["humidity_pct"])
        if last_dht is None:
            continue
        frames.append(
            build_telemetry(
                "pump-01",
                row["ts"],
                {
                    "temperature": last_dht[0],
                    "vibration": row["vibration_g_driver"],
                    "pressure": row["pressure_hpa"],
                    "humidity": last_dht[1],
                    "gas": gas(),
                    "current": row["current_a"],
                },
                i,
            )
        )
    return frames


# ---- pipeline -------------------------------------------------------------------


@dataclass
class Fitted:
    preprocessor: Preprocessor
    detector: IsolationForestDetector
    policy: SeverityThresholdFlagPolicy
    c: ConsistencyProvider
    rules: dict[str, object] = field(default_factory=dict)
    vibration_bands: StateBands = BENCH_VIBRATION_BANDS


def fit(frames: list[TelemetryMessage]) -> Fitted:
    pre = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW)
    windows = pre.process(frames)
    detector = IsolationForestDetector(flag_threshold=DETECTOR_THRESHOLD, random_state=0)
    policy = SeverityThresholdFlagPolicy()
    c = ConsistencyProvider()
    for target in (c, detector, policy):
        target.fit(windows)
    bands = calibrate_vibration_bands(
        [([f.sensors.current for f in frames], [f.sensors.vibration for f in frames])], WINDOW
    )
    rules = {}
    for name, variant in RULES.items():
        if variant.rule == "trend_sign":
            rule = TrendSignPhysicsRule()
        else:
            rule = OperatingStateRule(
                vibration_bands=bands if variant.calibrated else BENCH_VIBRATION_BANDS
            )
        rule.fit(windows)
        rules[name] = rule
    return Fitted(pre, detector, policy, c, rules, bands)


class BatchScoredDetector:
    """The fitted detector with one stream's window scores computed in a single
    batch. Scores are identical to per-window ``score()`` (same forest, same
    empirical-CDF severity); this only removes per-call overhead so both rules
    can be evaluated on many episodes. Keyed on window content."""

    def __init__(self, detector: IsolationForestDetector, windows) -> None:
        self.flag_threshold = detector.flag_threshold
        self._detector = detector
        self._scores: dict[tuple, float] = {}
        if windows:
            train = detector._require_fitted()
            raw = detector._anomaly_scores(detector._matrix(windows))
            for window, a in zip(windows, raw, strict=True):
                rank = int(np.searchsorted(train, float(a), side="right"))
                self._scores[self._key(window)] = rank / len(train)

    @staticmethod
    def _key(window) -> tuple:
        return tuple(v for row in window.as_matrix() for v in row)

    def score(self, window) -> float:
        hit = self._scores.get(self._key(window))
        return hit if hit is not None else self._detector.score(window)

    def flag(self, window) -> bool:
        return self.score(window) >= self.flag_threshold


def scored(fitted: Fitted, frames: list[TelemetryMessage]) -> BatchScoredDetector:
    return BatchScoredDetector(fitted.detector, fitted.preprocessor.process(frames))


def run(fitted: Fitted, rule_name: str, frames: list[TelemetryMessage], detector=None):
    """Fresh stateful parts (trust, h, k, c history, rule history) per run;
    fitted parts shared read-only."""
    pipeline = P2Pipeline(
        preprocessor=fitted.preprocessor,
        detector=detector if detector is not None else fitted.detector,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(copy.deepcopy(fitted.rules[rule_name])),
        c_provider=copy.deepcopy(fitted.c),
        k_provider=(
            OperatingStateCorrelationProvider(
                OperatingStateRule(vibration_bands=fitted.vibration_bands)
            )
            if RULES[rule_name].operating_state_k
            else CorrelationProvider(running_gate=BENCH_RUNNING_GATE)
        ),
        h_provider=HReliabilityProvider(),
        flag_policy=fitted.policy,
        physics_flags=RULES[rule_name].physics_flags,
    )
    return pipeline.process(frames)


# ---- scenarios ------------------------------------------------------------------


def _median(frames, channel) -> float:
    return statistics.median(getattr(f.sensors, channel) for f in frames)


def scenarios(channel: str, state: str) -> list[tuple[str, str, str, Callable[[int], Injection]]]:
    """(name, truth, family, factory(onset)) for one channel and motor state."""
    running = state == RUNNING
    if channel == "current":
        other_state_value = 0.0 if running else 0.8
        cross_bias = -0.8 if running else 0.6  # lands in the other state's band
        spike, drift, small_bias, cap = 0.6, 0.01, 0.02, 0.02
    else:
        other_state_value = 0.15 if running else 0.7
        cross_bias = -0.55 if running else 0.5
        spike, drift, small_bias, cap = 3.0, 0.01, 0.03, 0.03

    def ch(cls, **kw):
        return lambda onset: cls(channel=channel, onset=onset, **kw)

    return [
        ("spike (2 samples)", "fault", "fault", ch(Spike, duration=2, amplitude=spike)),
        ("stuck_at", "fault", "fault", ch(StuckAt, duration=DURATION)),
        ("drift", "fault", "fault", ch(Drift, duration=DURATION, rate=drift)),
        (
            "constant_spoof: cross state",
            "attack",
            "cross",
            ch(ConstantSpoof, duration=DURATION, value=other_state_value),
        ),
        (
            "bias_fdi: cross state",
            "attack",
            "cross",
            ch(BiasFDI, duration=DURATION, bias=cross_bias),
        ),
        ("replay: other state", "attack", "cross", None),  # built per onset below
        ("ramp_fdi", "attack", "ramp", ch(RampFDI, duration=DURATION, slope=drift)),
        ("constant_spoof: in state", "attack", "in-state", None),
        (
            "bias_fdi: in state",
            "attack",
            "in-state",
            ch(BiasFDI, duration=DURATION, bias=small_bias),
        ),
        (
            "stealth_fdi",
            "attack",
            "in-state",
            ch(AdaptiveStealthFDI, duration=DURATION, rate=cap / 10, residual_cap=cap),
        ),
    ]


def build_injection(name, factory, channel, frames, onset) -> Injection | None:
    if name == "constant_spoof: in state":
        value = _median(frames[onset - WINDOW : onset], channel)
        return ConstantSpoof(channel=channel, onset=onset, duration=DURATION, value=value)
    if name == "replay: other state":
        # Replay the most recent span whose motor state differs from now.
        bands = BENCH_CURRENT_BANDS
        now = bands.classify(_median(frames[onset - WINDOW : onset], "current"))
        for src in range(onset - DURATION - WINDOW, WINDOW, -10):
            span = frames[src : src + DURATION]
            if bands.classify(_median(span, "current")) not in (now, "unclear"):
                return Replay(channel=channel, onset=onset, duration=DURATION, source_onset=src)
        return None  # no other-state history (idle-only stream): not applicable
    return factory(onset)


# ---- evaluation -------------------------------------------------------------------


_BANDS = {"current": BENCH_CURRENT_BANDS, "vibration": BENCH_VIBRATION_BANDS}


def crosses_state(stream, channel, onset_local, duration) -> bool:
    """Measured, not assumed: does the injected reading ever claim the OTHER
    motor state (a full window inside the injection whose median lands in the
    opposite determinate band)? That is what makes an attack physically
    impossible; a reading that stays in its true state is physically
    plausible whatever its shape."""
    bands = _BANDS[channel]
    before = bands.classify(_median(stream[onset_local - WINDOW : onset_local], channel))
    if before == "unclear":
        return False
    for start in range(onset_local, onset_local + duration - WINDOW + 1):
        state = bands.classify(_median(stream[start : start + WINDOW], channel))
        if state not in ("unclear", before):
            return True
    return False


def score(outcomes, channel, onset, duration, offset):
    span = [
        o
        for o in outcomes
        if o.window.end_index + offset > onset and o.window.start_index + offset < onset + duration
    ]
    flagged = [o for o in span if o.channel_flags[channel]]
    if not flagged:
        return False, "missed", "missed", "missed"
    labels = [o.attribution[channel].attribution.value for o in flagged]
    first = labels[0]
    settled = Counter(labels).most_common(1)[0][0]
    # Episode verdict: a physics violation is decisive evidence, so an episode
    # in which ANY window was attributed attack is an attack episode. Scored on
    # faults too, so it cannot hide false accusations.
    episode = "attack" if "attack" in labels else "fault"
    return True, first, settled, episode


def evaluate_stream(name, frames, fit_fraction, max_onsets, out, spacing=SPACING):
    split = int(len(frames) * fit_fraction)
    fitted = fit(frames[:split])
    # Each episode runs on its own copy, so onsets closer than an episode's
    # length do not interact; spacing only limits correlation between them.
    onsets = list(range(split + WARMUP, len(frames) - DURATION - TAIL, spacing))[:max_onsets]
    results = out.setdefault(name, defaultdict(list))

    # clean control on (up to) the first CLEAN_CONTROL_FRAMES of the eval segment
    clean = frames[split : split + CLEAN_CONTROL_FRAMES]
    clean_detector = scored(fitted, clean)
    for rule_name in RULES:
        outcomes = run(fitted, rule_name, clean, clean_detector)
        labels = Counter(
            o.attribution[ch].attribution.value for o in outcomes for ch in ("current", "vibration")
        )
        results[("__clean__", rule_name)].append((len(outcomes) * 2, labels))

    for onset in onsets:
        state = (
            RUNNING
            if BENCH_CURRENT_BANDS.classify(_median(frames[onset - WINDOW : onset], "current"))
            == RUNNING
            else "idle"
        )
        for channel in ("current", "vibration"):
            for sc_name, truth, _family, factory in scenarios(channel, state):
                injection = build_injection(sc_name, factory, channel, frames, onset)
                if injection is None:
                    continue
                start = onset - WARMUP
                # Inject into this episode's slice only, with indices shifted into it.
                shift = {"onset": injection.onset - start}
                if isinstance(injection, Replay):
                    shift["source_onset"] = injection.source_onset - start
                    if shift["source_onset"] < 0:
                        start = injection.source_onset
                        shift = {"onset": injection.onset - start, "source_onset": 0}
                local = dataclasses.replace(injection, **shift)
                stream = local.apply(frames[start : onset + DURATION + TAIL]).frames
                episode_detector = scored(fitted, stream)
                for rule_name in RULES:
                    outcomes = run(fitted, rule_name, stream, episode_detector)
                    detected, first, settled, episode = score(
                        outcomes, channel, onset, injection.duration, start
                    )
                    if truth == "fault":
                        measured = "fault"
                    elif crosses_state(stream, channel, onset - start, injection.duration):
                        measured = "attack: crosses state"
                    else:
                        measured = "attack: stays in state"
                    results[(sc_name, rule_name)].append(
                        dict(
                            channel=channel,
                            state=state,
                            truth=truth,
                            family=measured,
                            detected=detected,
                            first=first,
                            settled=settled,
                            episode=episode,
                        )
                    )


def report(out) -> None:
    for stream, results in out.items():
        print(f"\n=== stream: {stream} ===")
        for rule_name in RULES:
            total, labels = 0, Counter()
            for n, c in results[("__clean__", rule_name)]:
                total += n
                labels.update(c)
            print(
                f"  clean control [{rule_name}]: {total} channel-windows -> "
                f"attack {labels['attack']} ({labels['attack'] / max(total, 1):.1%}), "
                f"fault {labels['fault']} ({labels['fault'] / max(total, 1):.1%})"
            )
        print(
            f"\n  {'scenario':30s} {'truth':6s} {'n':>3s} | "
            + " | ".join(f"{r[:16]:16s} det  first-ok  settled-ok" for r in RULES)
        )
        names = sorted(
            {k[0] for k in results if k[0] != "__clean__"},
            key=lambda n: [s[0] for s in scenarios("current", "idle")].index(n),
        )
        for sc in names:
            cells = []
            n = 0
            truth = ""
            for rule_name in RULES:
                rows = results[(sc, rule_name)]
                n = len(rows)
                truth = rows[0]["truth"] if rows else ""
                det = sum(r["detected"] for r in rows)
                first_ok = sum(r["first"] == r["truth"] for r in rows)
                settled_ok = sum(r["settled"] == r["truth"] for r in rows)
                cells.append(f"{'':16s} {det:>3d}  {first_ok:>8d}  {settled_ok:>10d}")
            print(f"  {sc:30s} {truth:6s} {n:>3d} | " + " | ".join(cells))
        for metric in ("settled", "episode"):
            print(f"\n  summary ({metric} attribution, detected episodes only):")
            for rule_name in RULES:
                fam = defaultdict(lambda: [0, 0])
                for (sc, rn), rows in results.items():
                    if rn != rule_name or sc == "__clean__":
                        continue
                    for r in rows:
                        if r["detected"]:
                            fam[r["family"]][1] += 1
                            fam[r["family"]][0] += r[metric] == r["truth"]
                parts = [
                    f"{f}: {ok}/{tot} ({ok / tot:.0%})"
                    for f, (ok, tot) in sorted(fam.items())
                    if tot
                ]
                print(f"    {rule_name:18s} " + "  ".join(parts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--idle", type=Path, default=Path("telemetry_capture_5sensor_nominal.jsonl")
    )
    parser.add_argument("--cycling", type=Path, default=Path("motor_load_full.jsonl"))
    parser.add_argument("--idle-onsets", type=int, default=12)
    parser.add_argument("--cycling-onsets", type=int, default=4)
    parser.add_argument("--running", type=Path, default=Path("motor_run_capture.jsonl"))
    parser.add_argument("--running-onsets", type=int, default=10)
    args = parser.parse_args(argv)

    out: dict = {}
    if args.idle.is_file():
        evaluate_stream("idle (7.2 h capture)", load_stream(args.idle), 0.1, args.idle_onsets, out)
    if args.cycling.is_file():
        evaluate_stream(
            f"cycling ({args.cycling.name})",
            load_stream(args.cycling),
            0.5,
            args.cycling_onsets,
            out,
        )
    if args.running.is_file():
        evaluate_stream(
            f"running ({args.running.name})",
            load_stream(args.running),
            0.35,
            args.running_onsets,
            out,
            spacing=60,
        )
    if not out:
        print("no capture files found", file=sys.stderr)
        return 1
    report(out)
    print(
        "\nNOTE: magnitudes are evaluation fixtures; episodes are real bench data with "
        "synthetic injections."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
