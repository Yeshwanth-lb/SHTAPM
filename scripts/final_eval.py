"""Run every bench evaluation on one capture and collect the results.

For the final baseline session: after recording a new clean capture (motor
cycling, real sensors), one command re-runs the evaluations the decision log
quotes and writes each report plus a short index to ``results/<capture stem>/``:

  1. baseline_check.txt   fit_p2_baseline hold-out check: false alarms, clean
                          trust (release, D037), band coverage (D038)
  2. attribution.txt      attribution_bench_eval with the capture as the cycling
                          stream (fault vs attack, false attacks on clean data)
  3. self_heal.txt        self_heal_eval on the capture (isolation, VIRTUAL
                          error, release)
  4. detector.txt         detector_bench_eval with the capture as the running
                          stream

Usage (repo root):
    python scripts/final_eval.py cycling_baseline.jsonl

Nothing here changes code or models; the baseline check saves its provisional
model into the results folder, not into ``models/``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(name: str, args: list[str], out_dir: Path, env: dict[str, str]) -> tuple[str, int, float]:
    started = time.monotonic()
    path = out_dir / f"{name}.txt"
    with path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            [sys.executable, *args], cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT
        )
    return name, result.returncode, time.monotonic() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("capture", type=Path, help="clean telemetry capture (JSONL)")
    parser.add_argument("--onsets", type=int, default=30, help="injection onsets per stream")
    args = parser.parse_args(argv)
    capture = args.capture.resolve()
    if not capture.is_file():
        print(f"capture not found: {capture}", file=sys.stderr)
        return 1
    out_dir = ROOT / "results" / capture.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    sep = ";" if os.name == "nt" else ":"
    env["PYTHONPATH"] = sep.join([str(ROOT / "backend"), str(ROOT)])
    missing = Path("does-not-exist.jsonl")

    jobs = [
        (
            "baseline_check",
            [
                "edge/scripts/fit_p2_baseline.py",
                str(capture),
                "--model-dir",
                str(out_dir / "provisional_model"),
            ],
        ),
        (
            "attribution",
            [
                "-m",
                "edge.eval.attribution_bench_eval",
                "--idle",
                str(missing),
                "--running",
                str(missing),
                "--cycling",
                str(capture),
                "--cycling-onsets",
                str(args.onsets),
            ],
        ),
        (
            "self_heal",
            [
                "-m",
                "edge.eval.self_heal_eval",
                "--idle",
                str(missing),
                "--running",
                str(capture),
                "--onsets",
                str(min(args.onsets, 12)),
            ],
        ),
        (
            "detector",
            [
                "-m",
                "edge.eval.detector_bench_eval",
                "--idle",
                str(missing),
                "--running",
                str(capture),
            ],
        ),
    ]
    index = [f"# Final evaluation: {capture.name}", ""]
    for name, job_args in jobs:
        print(f"running {name} ...", flush=True)
        _, code, seconds = _run(name, job_args, out_dir, env)
        status = "ok" if code == 0 else f"FAILED (exit {code})"
        index.append(f"- {name}.txt: {status}, {seconds:.0f} s")
        print(f"  {status} in {seconds:.0f} s -> {out_dir / (name + '.txt')}")
    (out_dir / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"\nall reports in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
