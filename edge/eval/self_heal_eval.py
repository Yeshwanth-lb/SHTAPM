"""Self-healing quantified on real bench streams (FR-H1..H4, O6, NFR-P3).

Diagnostic/offline tooling: not production, not imported by ``edge/main.py``.

WHAT IS MEASURED. A falsification is injected into a real capture and the
exact live composition (``edge.main._build_p2_monitor``: persisted baseline,
Isolation Forest, trust, D034 attribution with physics flags, isolation
tracker, trained digital twin) processes it frame by frame, as on the Pi.
Because the injection is synthetic on top of real data, the TRUE reading is
known at every sample, so the twin's reconstruction can be scored against it:

  * time to isolate      onset -> first window with the channel isolated
  * VIRTUAL coverage     share of attack samples served by the twin
  * reconstruction error |twin - truth| vs |what the sensor claimed - truth|,
                         i.e. how much error self-healing removes for an
                         operator reading the channel during the attack
  * time to release      attack end -> channel released (D018 pt.2)
  * clean control        isolation episodes per hour and share of samples
                         isolated on uninjected data (false isolation)

Only ``current`` can be substituted (the one trained twin, 45.8% skill on its
training capture); attacks are injected on current. The twin was trained on
2026-09-18 data, so every other capture is out of its training period: the
errors below include that distribution shift, honestly.

Run (repo root):
    PYTHONPATH="backend;." python -m edge.eval.self_heal_eval
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from edge.anomaly.operating_state_rule import BENCH_CURRENT_BANDS, RUNNING
from edge.anomaly.preprocess import Preprocessor
from edge.eval.attribution_bench_eval import load_stream
from edge.injection import BiasFDI, ConstantSpoof, Injection
from edge.main import _build_p2_monitor, _load_self_heal
from edge.models.p2_baseline import build_baseline

WINDOW = 30
WARMUP = 150
DURATION = 60
TAIL = 240  # default observation after the attack; idle uses longer (see main)


class _Capture:
    def __init__(self) -> None:
        self.messages: list = []

    def publish(self, message) -> None:
        self.messages.append(message)


@dataclass
class EpisodeResult:
    scenario: str
    state: str
    isolated_after: int | None  # samples after onset
    coverage: float
    twin_mae: float | None
    sensor_mae: float
    released_after: int | None  # samples after the attack ended
    n_substitutions: int


@dataclass
class StreamSummary:
    episodes: list[EpisodeResult] = field(default_factory=list)
    clean_hours: float = 0.0
    clean_isolation_episodes: int = 0
    clean_isolated_share: float = 0.0


def _process(frames, baseline, model_dir):
    """Run the live composition over ``frames``; return per-frame isolation
    state, substitution flags and the twin's reconstructed value per frame."""
    runtime = _load_self_heal(model_dir, WINDOW)
    if runtime is None:
        raise SystemExit(f"no trained twin in {model_dir}: substitution cannot be evaluated")
    twin_values: dict[int, float] = {}
    frame_index = {"i": -1}
    original = runtime.substitute

    def recording_substitute(outcome, isolated, recent):
        reports = original(outcome, isolated, recent)
        for report in reports:
            twin_values[frame_index["i"]] = report.substituted_value
        return reports

    runtime.substitute = recording_substitute
    capture = _Capture()
    recent: deque = deque(maxlen=WINDOW)
    monitor = _build_p2_monitor(
        fit_window_count=None,
        device_id="pump-01",
        decision_publisher=capture,
        self_heal=runtime,
        recent_frames=recent,
        baseline=baseline,
    )
    for i, frame in enumerate(frames):
        frame_index["i"] = i
        recent.append(frame)
        monitor.on_frame(frame)
    n = len(frames)
    isolated = [False] * n
    substituted = [False] * n
    # Message k is emitted at frame k + WINDOW - 1 (first full window).
    for k, m in enumerate(capture.messages):
        i = k + WINDOW - 1
        if i < n:
            isolated[i] = "current" in [c.value for c in m.tracked_isolation_candidates]
            substituted[i] = "current" in [c.value for c in m.substituted_channels]
    return isolated, substituted, twin_values


def _scenarios(state: str) -> list[tuple[str, Injection]]:
    running = state == RUNNING
    return [
        (
            "constant spoof (crosses state)",
            ConstantSpoof(
                channel="current", onset=WARMUP, duration=DURATION, value=0.0 if running else 0.8
            ),
        ),
        (
            "bias (crosses state)",
            BiasFDI(
                channel="current", onset=WARMUP, duration=DURATION, bias=-0.8 if running else 0.6
            ),
        ),
    ]


def evaluate(
    name, frames, fit_fraction, n_onsets, spacing, clean_frames, model_dir, out, tail=TAIL
):
    split = int(len(frames) * fit_fraction)
    pre = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW)
    baseline = build_baseline(frames[:split], source=name, preprocessor=pre)
    summary = out.setdefault(name, StreamSummary())

    clean = frames[split : split + clean_frames]
    iso, _, _ = _process(clean, baseline, model_dir)
    summary.clean_isolation_episodes = sum(
        1 for a, b in zip([False] + iso, iso, strict=False) if b and not a
    )
    summary.clean_isolated_share = sum(iso) / max(len(iso), 1)
    secs = (_ts(clean[-1]) - _ts(clean[0])) if len(clean) > 1 else 0.0
    summary.clean_hours = secs / 3600

    onsets = list(range(split + WARMUP, len(frames) - DURATION - tail, spacing))[:n_onsets]
    for onset in onsets:
        state = BENCH_CURRENT_BANDS.classify(
            statistics.median(f.sensors.current for f in frames[onset - WINDOW : onset])
        )
        if state == "unclear":
            continue
        segment = frames[onset - WARMUP : onset + DURATION + tail]
        for scenario, injection in _scenarios(state):
            injected = injection.apply(segment).frames
            iso, sub, twin = _process(injected, baseline, model_dir)
            attack = range(WARMUP, WARMUP + DURATION)
            isolated_after = next((i - WARMUP for i in attack if iso[i]), None)
            coverage = sum(sub[i] for i in attack) / DURATION
            truth = [segment[i].sensors.current for i in attack]
            claimed = [injected[i].sensors.current for i in attack]
            sensor_mae = statistics.mean(abs(c - t) for c, t in zip(claimed, truth, strict=True))
            twin_err = [abs(twin[i] - segment[i].sensors.current) for i in attack if i in twin]
            end = WARMUP + DURATION
            released_after = (
                next((i - end for i in range(end, len(iso)) if not iso[i]), None)
                if any(iso[i] for i in attack)
                else None
            )
            summary.episodes.append(
                EpisodeResult(
                    scenario=scenario,
                    state=state,
                    isolated_after=isolated_after,
                    coverage=coverage,
                    twin_mae=statistics.mean(twin_err) if twin_err else None,
                    sensor_mae=sensor_mae,
                    released_after=released_after,
                    n_substitutions=len(twin_err),
                )
            )


def _ts(frame) -> float:
    from datetime import datetime

    return datetime.fromisoformat(frame.ts.replace("Z", "+00:00")).timestamp()


def _fmt(values, unit="") -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "n/a"
    lo, hi, mid = min(values), max(values), statistics.median(values)
    return f"median {mid:.3g}{unit} (min {lo:.3g}, max {hi:.3g}, n={len(values)})"


def report(out) -> None:
    for name, s in out.items():
        print(f"\n=== {name} ===")
        print(
            f"  clean control: {s.clean_hours:.2f} h -> {s.clean_isolation_episodes} false "
            f"isolation episode(s), {s.clean_isolated_share:.2%} of samples isolated"
        )
        for scenario in sorted({e.scenario for e in s.episodes}):
            eps = [e for e in s.episodes if e.scenario == scenario]
            isolated = [e for e in eps if e.isolated_after is not None]
            print(f"\n  {scenario}: {len(isolated)}/{len(eps)} episodes isolated")
            to_isolate = _fmt([e.isolated_after for e in isolated], " samples")
            print(f"    time to isolate     : {to_isolate}")
            print(f"    VIRTUAL coverage    : {_fmt([e.coverage for e in eps])}")
            print(f"    sensor error (no heal): {_fmt([e.sensor_mae for e in eps], ' A')}")
            print(f"    twin error (healed)   : {_fmt([e.twin_mae for e in eps], ' A')}")
            to_release = _fmt([e.released_after for e in isolated], " samples")
            print(f"    time to release     : {to_release}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--idle", type=Path, default=Path("telemetry_capture_5sensor_nominal.jsonl")
    )
    parser.add_argument("--running", type=Path, default=Path("motor_run_capture.jsonl"))
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--onsets", type=int, default=8)
    args = parser.parse_args(argv)
    out: dict = {}
    if args.idle.is_file():
        evaluate(
            "idle (7.2 h capture)",
            load_stream(args.idle),
            0.1,
            args.onsets,
            1200,
            3600,
            args.model_dir,
            out,
            tail=720,  # ~14 min: idle trust can take minutes to recover
        )
    if args.running.is_file():
        evaluate(
            "running (2026-10-26 capture)",
            load_stream(args.running),
            0.35,
            args.onsets,
            60,
            400,
            args.model_dir,
            out,
        )
    if not out:
        print("no capture files found", file=sys.stderr)
        return 1
    report(out)
    print(
        "\nNOTE: injected falsifications on real bench data; the twin was trained on 2026-09-18 "
        "data, so other captures include distribution shift. 1 sample ~ 1.2 s on this bench."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
