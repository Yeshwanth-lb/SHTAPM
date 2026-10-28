"""Detector candidates on REAL bench streams (complements swat_ablation.py, O10).

Diagnostic/offline tooling: not production, not imported by ``edge/main.py``.

WHY. The SWaT ablation (EVALUATION_RESULTS_2026-10-26.md §5) left no single
winner: the z-score is precise but misses most attack events, the combined
max(z-score, IF + low-pass) catches the most events fastest, and the deployed
IF (identity filters, per-window min-max) is the weakest IF option. Before the
live detector changes, the same candidates are compared on this bench's own
data with the same injections the attribution harness uses.

CANDIDATES (window = 30, each turned into an empirical-CDF severity against its
OWN fit windows, so a threshold means the same nominal clean-flag rate for all):
  if_identity      deployed: IF over per-window min-max windows
  if_lowpass       IF over per-window min-max windows, EMA alpha 0.3
  zscore           max over channels of the window's RMS z-score (raw, fit stats)
  if_global_z      IF over windows of globally standardised raw values
  max_z_iflowpass  per window, max(zscore, if_lowpass) severity

METRICS at fixed thresholds 0.95 / 0.99 (chosen from clean data only):
  * clean flag rate on an uninjected eval segment (false alarms)
  * per injected episode: detected (any overlapping window flagged) and delay
    from onset to first flag, in samples

Run (repo root):
    PYTHONPATH="backend;." python -m edge.eval.detector_bench_eval
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from app.schemas.contracts import CHANNELS, TelemetryMessage
from sklearn.ensemble import IsolationForest

from edge.anomaly.operating_state_rule import BENCH_CURRENT_BANDS, RUNNING
from edge.anomaly.preprocess import Preprocessor
from edge.eval.attribution_bench_eval import build_injection, load_stream, scenarios

WINDOW = 30
WARMUP = 120
DURATION = 60
TAIL = 30
THRESHOLDS = (0.95, 0.99)
LOWPASS_ALPHA = 0.3  # same ablation fixture as swat_ablation.py
CANDIDATES = ("if_identity", "if_lowpass", "zscore", "if_global_z", "max_z_iflowpass")


def _ecdf(fit: np.ndarray, scores: np.ndarray) -> np.ndarray:
    ordered = np.sort(fit)
    return np.searchsorted(ordered, scores, side="right") / len(ordered)


def _raw(frames: list[TelemetryMessage]) -> np.ndarray:
    return np.array([[float(getattr(f.sensors, ch)) for ch in CHANNELS] for f in frames])


class Detectors:
    """All candidates fitted on one stream's clean fit segment."""

    def __init__(self, fit_frames: list[TelemetryMessage]) -> None:
        self._pre = {
            "identity": Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=WINDOW),
            "lowpass": Preprocessor(
                median_kernel=1, low_pass_alpha=LOWPASS_ALPHA, window_size=WINDOW
            ),
        }
        raw = _raw(fit_frames)
        self._mean, self._std = raw.mean(axis=0), raw.std(axis=0) + 1e-8
        self._forests: dict[str, IsolationForest] = {}
        self._fit_scores: dict[str, np.ndarray] = {}
        for name, x in self._features(fit_frames).items():
            if name == "zscore":
                self._fit_scores[name] = x
                continue
            forest = IsolationForest(random_state=0).fit(x)
            self._forests[name] = forest
            self._fit_scores[name] = -forest.score_samples(x)

    def _features(self, frames: list[TelemetryMessage]) -> dict[str, np.ndarray]:
        out = {}
        for key, pre in self._pre.items():
            windows = pre.process(frames)
            out[f"if_{key}"] = np.stack(
                [np.asarray(w.as_matrix(), dtype=float).reshape(-1) for w in windows]
            )
        z = (_raw(frames) - self._mean) / self._std
        starts = range(0, len(frames) - WINDOW + 1)
        out["if_global_z"] = np.stack([z[s : s + WINDOW].reshape(-1) for s in starts])
        out["zscore"] = np.array(
            [np.sqrt((z[s : s + WINDOW] ** 2).mean(axis=0)).max() for s in starts]
        )
        return out

    def severities(self, frames: list[TelemetryMessage]) -> dict[str, np.ndarray]:
        """Per-window severity for every candidate; index i = window ending
        at sample i + WINDOW - 1."""
        sev = {}
        for name, x in self._features(frames).items():
            raw = x if name == "zscore" else -self._forests[name].score_samples(x)
            sev[name] = _ecdf(self._fit_scores[name], raw)
        sev["max_z_iflowpass"] = np.maximum(sev["zscore"], sev["if_lowpass"])
        return sev


def evaluate(name, frames, fit_fraction, n_onsets, spacing, clean_frames, out):
    split = int(len(frames) * fit_fraction)
    det = Detectors(frames[:split])
    res = out.setdefault(name, {"clean": {}, "episodes": defaultdict(list)})

    clean = det.severities(frames[split : split + clean_frames])
    for cand in CANDIDATES:
        for t in THRESHOLDS:
            res["clean"][(cand, t)] = float((clean[cand] >= t).mean())

    onsets = list(range(split + WARMUP, len(frames) - DURATION - TAIL, spacing))[:n_onsets]
    for onset in onsets:
        state = (
            RUNNING
            if BENCH_CURRENT_BANDS.classify(
                statistics.median(f.sensors.current for f in frames[onset - WINDOW : onset])
            )
            == RUNNING
            else "idle"
        )
        for channel in ("current", "vibration"):
            for sc_name, truth, _family, factory in scenarios(channel, state):
                injection = build_injection(sc_name, factory, channel, frames, onset)
                if injection is None or sc_name.startswith("replay"):
                    continue
                start = onset - WARMUP
                local = type(injection)(**{**injection.__dict__, "onset": injection.onset - start})
                stream = local.apply(frames[start : onset + DURATION + TAIL]).frames
                sev = det.severities(stream)
                for cand in CANDIDATES:
                    for t in THRESHOLDS:
                        # windows overlapping the injection: end >= onset, start < onset+dur
                        first = None
                        for i, s in enumerate(sev[cand]):
                            w_start, w_end = i, i + WINDOW - 1
                            if w_end < WARMUP or w_start >= WARMUP + injection.duration:
                                continue
                            if s >= t:
                                first = w_end - WARMUP
                                break
                        res["episodes"][(cand, t)].append((sc_name, truth, first))


def report(out) -> None:
    for name, res in out.items():
        print(f"\n=== {name} ===")
        print(
            f"  {'candidate':16s} {'thr':>5s} | {'clean flag':>10s} | "
            f"{'faults det':>10s} | {'attacks det':>11s} | median delay (samples)"
        )
        for t in THRESHOLDS:
            for cand in CANDIDATES:
                eps = res["episodes"][(cand, t)]
                faults = [e for e in eps if e[1] == "fault"]
                attacks = [e for e in eps if e[1] == "attack"]
                delays = [e[2] for e in eps if e[2] is not None]
                fd = sum(e[2] is not None for e in faults)
                ad = sum(e[2] is not None for e in attacks)
                med = statistics.median(delays) if delays else float("nan")
                print(
                    f"  {cand:16s} {t:5.2f} | {res['clean'][(cand, t)]:10.1%} | "
                    f"{fd:4d}/{len(faults):<5d} | {ad:5d}/{len(attacks):<5d} | {med:.0f}"
                )
            print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--idle", type=Path, default=Path("telemetry_capture_5sensor_nominal.jsonl")
    )
    parser.add_argument("--running", type=Path, default=Path("motor_run_capture.jsonl"))
    parser.add_argument("--onsets", type=int, default=20)
    args = parser.parse_args(argv)
    out: dict = {}
    if args.idle.is_file():
        evaluate("idle (7.2 h capture)", load_stream(args.idle), 0.1, args.onsets, 240, 2400, out)
    if args.running.is_file():
        evaluate(
            f"running ({args.running.name})", load_stream(args.running), 0.35, 10, 60, 400, out
        )
    if not out:
        print("no capture files found", file=sys.stderr)
        return 1
    report(out)
    print(
        "NOTE: injected faults/attacks on real bench data; thresholds are nominal clean-flag "
        "rates from each candidate's own fit, no attack labels used to choose them."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
