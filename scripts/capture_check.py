"""Quick sanity check of a baseline capture WHILE it is still recording.

The 2026-10-28 baseline lost its vibration channel two minutes in (the ADXL
shifted on the first motor run: idle read ~2.7 g instead of ~0.05 g) and it was
only found after the full 70 minutes. Run this on the Pi a few minutes into a
recording, and again later, to catch that kind of problem early:

    python3 scripts/capture_check.py ~/SHTAPM/final_baseline.jsonl

It splits the frames by motor state using the current (idle < 0.05 A, running
> 0.3 A) and reports, per 5-minute block, the idle and running vibration
medians, so a sensor that moved shows up as a jump in the idle level or as
running no longer standing apart from idle. It also reports frame gaps and
missing channel values.

Standard library only (runs with the Pi's system python). Exit status 1 when
something is wrong, 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

CHANNELS = ("temperature", "vibration", "pressure", "humidity", "gas", "current")
IDLE_MAX_A = 0.05
RUNNING_MIN_A = 0.3
BLOCK_S = 300.0
# Bench reference (cycling_capture_2026-10-27, 70 min): idle vibration
# 0.07-0.15 g, running 0.49-0.67 g per 5-minute block. A still motor reading more
# than this means the zero point moved (sensor shifted or a loose axis wire).
IDLE_VIBRATION_MAX_G = 0.5
# Running must stand clearly above idle for the motor-state rule (D038).
SEPARATION_FACTOR = 2.0
GAP_S = 3.0


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def load_frames(path: Path) -> list[dict]:
    frames = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            frame = json.loads(line)
            frame["_t"] = _ts(frame["ts"])
        except (ValueError, KeyError, TypeError):
            continue  # a partly written last line while recording
        frames.append(frame)
    return frames


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _fmt(value: float | None) -> str:
    return "   -  " if value is None else f"{value:6.2f}"


def check(frames: list[dict]) -> tuple[list[str], list[str]]:
    """Return (report lines, problems)."""
    if not frames:
        return [], ["no readable frames yet"]
    lines: list[str] = []
    problems: list[str] = []
    start = frames[0]["_t"]
    minutes = (frames[-1]["_t"] - start).total_seconds() / 60
    lines.append(f"{len(frames)} frames, {minutes:.1f} min")

    gaps = [
        (b["_t"] - a["_t"]).total_seconds()
        for a, b in zip(frames, frames[1:], strict=False)
        if (b["_t"] - a["_t"]).total_seconds() > GAP_S
    ]
    if gaps:
        problems.append(f"{len(gaps)} gap(s) over {GAP_S:.0f} s, longest {max(gaps):.0f} s")
    for channel in CHANNELS:
        missing = sum(1 for f in frames if f.get("sensors", {}).get(channel) is None)
        if missing:
            problems.append(f"{channel}: {missing} frame(s) without a value")

    lines.append("")
    lines.append("block   idle vib (g)  running vib (g)  motor on")
    blocks: dict[int, list[dict]] = {}
    for frame in frames:
        blocks.setdefault(int((frame["_t"] - start).total_seconds() // BLOCK_S), []).append(frame)
    all_idle: list[float] = []
    all_running: list[float] = []
    for index in sorted(blocks):
        idle, running = [], []
        for frame in blocks[index]:
            sensors = frame.get("sensors", {})
            current, vibration = sensors.get("current"), sensors.get("vibration")
            if current is None or vibration is None:
                continue
            if current < IDLE_MAX_A:
                idle.append(vibration)
            elif current > RUNNING_MIN_A:
                running.append(vibration)
        all_idle += idle
        all_running += running
        on = 100 * len(running) / len(blocks[index])
        idle_med, run_med = _median(idle), _median(running)
        lines.append(
            f"{index * 5:3d}-{index * 5 + 5:<3d} {_fmt(idle_med)}        {_fmt(run_med)}"
            f"          {on:3.0f}%"
        )
        if idle_med is not None and idle_med > IDLE_VIBRATION_MAX_G:
            problems.append(
                f"minute {index * 5}-{index * 5 + 5}: motor off but vibration reads "
                f"{idle_med:.2f} g -- the ADXL moved or a wire is loose"
            )

    idle_med, run_med = _median(all_idle), _median(all_running)
    if run_med is None:
        lines.append("\nno running samples yet (motor never on above 0.3 A)")
    elif idle_med is not None and run_med < SEPARATION_FACTOR * idle_med:
        problems.append(
            f"running vibration ({run_med:.2f} g) does not stand apart from idle "
            f"({idle_med:.2f} g): the motor-state rule cannot tell on from off"
        )
    return lines, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("capture", type=Path, help="telemetry capture being recorded (JSONL)")
    args = parser.parse_args(argv)
    if not args.capture.is_file():
        print(f"capture not found: {args.capture}", file=sys.stderr)
        return 1
    lines, problems = check(load_frames(args.capture))
    print("\n".join(lines))
    print()
    if problems:
        for problem in problems:
            print(f"PROBLEM: {problem}")
        return 1
    print("OK: no problems found so far")
    return 0


if __name__ == "__main__":
    sys.exit(main())
