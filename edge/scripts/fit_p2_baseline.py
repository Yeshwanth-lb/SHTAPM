"""Build the persisted P2 clean baseline from a recorded telemetry capture (D031).

Record clean telemetry on the Pi while ``shtapm.service`` runs, in the same
conditions the system will be judged in (motor running for the demo):

    timeout 3600 mosquitto_sub -h localhost -t 'shtapm/pump-01/telemetry' \\
        > baseline_capture.jsonl

then, on the Pi, from the repo root:

    PYTHONPATH=backend:. .venv/bin/python edge/scripts/fit_p2_baseline.py \\
        baseline_capture.jsonl --model-dir models
    sudo systemctl restart shtapm

HOLD-OUT CHECK (on by default, ``--no-check`` skips it): before saving, the
capture is split in time -- the first ``--fit-fraction`` builds a provisional
baseline, and the real live composition (``edge.main._build_p2_monitor``, the
same code the service runs) scores the LATER remainder. Every held-out window
is clean by construction, so every isolation candidate it reports is a false
alarm. The saved baseline is then built from the WHOLE capture. The check
reports evidence; it does not gate saving, because no project document sets an
acceptable false-alarm rate.

It also reports each channel's median clean trust. An isolated channel is
released only at trust >= TRUSTED_MIN (D018 pt.2), so a channel whose CLEAN
trust sits below that would stay isolated forever after an attack. Measured on
the 7.2 h idle capture (D037): baselines of 36 and 43 min left idle `current`
at 0.60 and 0.69 (never released), 51 and 71 min at 0.82 and 0.87 (released
35-37 samples after the attack ended) -- the INA219's idle texture changed
during the first hour, and a baseline that misses the later regime makes a
normal 0 A window look unusual. A warning names such channels.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
from collections import Counter
from pathlib import Path

from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Preprocessor
from edge.models.p2_baseline import (
    DEFAULT_MAX_GAP_S,
    RECOMMENDED_MIN_SECONDS,
    build_baseline,
    parse_capture,
    save_baseline,
    split_segments,
)
from edge.trust.beta import TRUSTED_MIN

# Must match edge/main.py's live Preprocessor exactly: the baseline is only
# valid for the windowing it was built with (P2Baseline.windows() enforces it).
LIVE_MEDIAN_KERNEL = 1
LIVE_LOW_PASS_ALPHA = 1.0


class _CapturingPublisher:
    """Stands in for DecisionDiagnosticPublisher: keeps messages in memory."""

    def __init__(self) -> None:
        self.messages: list = []

    def publish(self, message) -> None:
        self.messages.append(message)


def _holdout_check(messages, *, fit_fraction: float, max_gap_s: float, preprocessor) -> int:
    from edge.main import _build_p2_monitor  # the live composition, unmodified

    ordered = [m for seg in split_segments(messages, max_gap_s) for m in seg]
    split = int(len(ordered) * fit_fraction)
    fit_part, eval_part = ordered[:split], ordered[split:]
    try:
        provisional = build_baseline(
            fit_part, source="holdout-fit", preprocessor=preprocessor, max_gap_s=max_gap_s
        )
    except ValueError as e:
        print(f"hold-out check skipped: fit portion unusable ({e})")
        return 0

    publisher = _CapturingPublisher()
    eval_windows = 0
    for segment in split_segments(eval_part, max_gap_s):
        # A fresh monitor per segment: the live rolling buffer never spans an
        # outage either, and trust state restarts with the process.
        monitor = _build_p2_monitor(
            fit_window_count=None,
            device_id=segment[0].device_id,
            decision_publisher=publisher,
            baseline=provisional,
        )
        for frame in segment:
            monitor.on_frame(frame)
    eval_windows = len(publisher.messages)
    if eval_windows == 0:
        print("hold-out check skipped: held-out portion is shorter than one window")
        return 0

    flagged = sum(1 for m in publisher.messages if m.anomaly_flag)
    candidate_counts = Counter(ch for m in publisher.messages for ch in m.isolation_candidates)
    tracked_at_end = publisher.messages[-1].tracked_isolation_candidates
    print(
        f"\nHOLD-OUT CHECK  fit on first {fit_fraction:.0%} "
        f"({provisional.duration_s / 60:.1f} min), scored the later "
        f"{eval_windows} windows (all clean, so every alarm is false):"
    )
    print(f"  anomaly-flagged windows : {flagged}/{eval_windows} ({flagged / eval_windows:.1%})")
    for ch in CHANNELS:
        n = candidate_counts.get(ch, 0)
        print(f"  {ch:12s} Malicious  : {n:5d}/{eval_windows} ({n / eval_windows:.1%})")
    print(f"  channels isolated at the end : {tracked_at_end or 'none'}")
    clean_trust = {
        ch: statistics.median(getattr(m.trust, ch) for m in publisher.messages) for ch in CHANNELS
    }
    print("  median clean trust  : " + ", ".join(f"{ch} {t:.2f}" for ch, t in clean_trust.items()))
    unreleasable = [ch for ch, t in clean_trust.items() if t < TRUSTED_MIN]
    if unreleasable:
        print(
            f"WARNING: clean trust below {TRUSTED_MIN} for {unreleasable}: once isolated, "
            "these channels would not be released (D018 pt.2, D037). Record a longer "
            "baseline that covers the operating conditions."
        )
    return eval_windows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("capture", type=Path, help="mosquitto_sub telemetry capture (JSONL)")
    parser.add_argument("--model-dir", type=Path, default=Path("models"))
    parser.add_argument("--max-gap-s", type=float, default=DEFAULT_MAX_GAP_S)
    parser.add_argument("--window-size", type=int, default=30)
    parser.add_argument("--fit-fraction", type=float, default=0.8)
    parser.add_argument("--no-check", action="store_true", help="skip the hold-out check")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if not 0.0 < args.fit_fraction < 1.0:
        print("ERROR: --fit-fraction must be between 0 and 1", file=sys.stderr)
        return 2
    if not args.capture.is_file():
        print(f"ERROR: capture not found: {args.capture}", file=sys.stderr)
        return 2

    with args.capture.open(encoding="utf-8", errors="replace") as fh:
        parsed = parse_capture(fh)
    print(
        f"capture: {len(parsed.messages)} valid frames, "
        f"{parsed.rejected_line_count} malformed lines skipped"
    )

    preprocessor = Preprocessor(
        median_kernel=LIVE_MEDIAN_KERNEL,
        low_pass_alpha=LIVE_LOW_PASS_ALPHA,
        window_size=args.window_size,
    )
    try:
        baseline = build_baseline(
            parsed.messages,
            source=args.capture.name,
            preprocessor=preprocessor,
            max_gap_s=args.max_gap_s,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(
        f"baseline: {baseline.frame_count} frames in {len(baseline.segments)} segment(s), "
        f"{baseline.window_count()} windows, {baseline.duration_s / 60:.1f} min clean"
    )
    if baseline.duration_s < RECOMMENDED_MIN_SECONDS:
        print(
            f"WARNING: under {RECOMMENDED_MIN_SECONDS // 60} min. The 2026-10-26 replay "
            "still produced false Malicious windows below that (D031). Record longer "
            "if you can."
        )

    if not args.no_check:
        _holdout_check(
            parsed.messages,
            fit_fraction=args.fit_fraction,
            max_gap_s=args.max_gap_s,
            preprocessor=preprocessor,
        )

    npz_path, json_path = save_baseline(baseline, args.model_dir)
    print(f"\nsaved: {npz_path} + {json_path}")
    print("restart the service to use it:  sudo systemctl restart shtapm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
