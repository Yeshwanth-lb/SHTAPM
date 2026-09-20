"""Find every real physical fault event in a load_capture.py bench diagnostic
JSONL, purely from the data -- no assumed timing (U07 fault-injection session).

Diagnostic/offline tooling: not production, not imported by ``edge/main.py``,
not on any acceptance path. Reads the per-sensor bench-diagnostic format
``edge/scripts/load_capture.py`` emits (current_a/adc_x.../temperature_c/...,
each with a paired ``*_healthy`` flag) -- NOT the published six-channel
TelemetryMessage format ``edge/eval/u05_capture_loader.py`` reads, because this
capture is deliberately taken with ``shtapm.service`` stopped so every sensor's
own health is visible independently of the all-six-healthy publish gate.

WHY: labels a capture's fault episodes from first principles so a companion
script (``bench_fault_injection_eval.py``) can check what the real P2 pipeline
did during them, without hand-picking timestamps from memory.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime


def _rel_t(row: dict, t0: datetime) -> float:
    t = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
    return (t - t0).total_seconds()


def _find_runs(mask: list[bool]) -> list[tuple[int, int]]:
    """[(start_idx, end_idx_inclusive), ...] for contiguous True runs."""
    runs = []
    start = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def _rolling_sd(series: list[float], w: int) -> list[float]:
    out = []
    for i in range(len(series)):
        lo, hi = max(0, i - w // 2), min(len(series), i + w // 2 + 1)
        window = series[lo:hi]
        out.append(statistics.pstdev(window) if len(window) > 1 else 0.0)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="load_capture.py JSONL output")
    args = parser.parse_args()

    rows = []
    with open(args.capture, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    n = len(rows)
    t0 = datetime.fromisoformat(rows[0]["ts"].replace("Z", "+00:00"))

    def rel_t(row: dict) -> float:
        return _rel_t(row, t0)

    print(f"samples: {n}   duration: {rel_t(rows[-1]):.1f}s ({rel_t(rows[-1]) / 60:.2f} min)")

    def report_runs(label: str, runs: list[tuple[int, int]], min_len: int = 1) -> None:
        print(f"\n--- {label}: {len(runs)} episode(s) ---")
        for a, b in runs:
            if (b - a + 1) < min_len:
                continue
            print(
                f"  idx {a:>4}-{b:<4}  t={rel_t(rows[a]):>6.1f}s -> {rel_t(rows[b]):>6.1f}s  "
                f"dur={rel_t(rows[b]) - rel_t(rows[a]):>5.1f}s  n={b - a + 1}"
            )

    # ---- 1. DHT22 dropout (temperature/humidity unhealthy) --------------------
    dht_bad = [not (r["temperature_healthy"] and r["humidity_healthy"]) for r in rows]
    report_runs("DHT22 fault (temp/humidity unhealthy)", _find_runs(dht_bad))

    # ---- 2. Vibration activity spike -------------------------------------------
    ax = [r["adc_x"] for r in rows]
    ay = [r["adc_y"] for r in rows]
    az = [r["adc_z"] for r in rows]
    w = 3
    act = [
        (a**2 + b**2 + c**2) ** 0.5
        for a, b, c in zip(_rolling_sd(ax, w), _rolling_sd(ay, w), _rolling_sd(az, w), strict=True)
    ]
    med_act = statistics.median(act)
    mad_act = statistics.median([abs(v - med_act) for v in act]) or 1e-9
    vib_spike = [abs(v - med_act) / mad_act > 6 for v in act]
    report_runs("Vibration spike (robust z>6 on 3-axis activity)", _find_runs(vib_spike))
    print(
        f"  (baseline activity median={med_act:.2f}, MAD={mad_act:.2f}; "
        f"peak activity={max(act):.2f} at t={rel_t(rows[act.index(max(act))]):.1f}s)"
    )

    # ---- 3. Pressure deviation ---------------------------------------------------
    press = [r["pressure_hpa"] for r in rows]
    med_p = statistics.median(press)
    mad_p = statistics.median([abs(v - med_p) for v in press]) or 1e-9
    press_dev = [abs(v - med_p) / mad_p > 6 for v in press]
    report_runs("Pressure deviation (robust z>6)", _find_runs(press_dev))
    print(
        f"  (baseline pressure median={med_p:.3f} hPa; "
        f"max deviation={max(abs(v - med_p) for v in press):.3f} hPa)"
    )

    # ---- 4. Current / motor episodes ---------------------------------------------
    thresh = 0.05
    cur = [r["current_a"] if r["current_a"] is not None else 0.0 for r in rows]
    motor_on = [c > thresh for c in cur]
    report_runs("Motor ON (current > 0.05A)", _find_runs(motor_on))

    deltas = [(cur[i + 1] - cur[i], i) for i in range(len(cur) - 1)]
    biggest_drop = min(deltas, key=lambda d: d[0])
    print("\n--- Largest single-sample current drop ---")
    print(
        f"  idx {biggest_drop[1]}->{biggest_drop[1] + 1}  t={rel_t(rows[biggest_drop[1]]):.1f}s  "
        f"delta={biggest_drop[0]:.4f} A  "
        f"({cur[biggest_drop[1]]:.4f} -> {cur[biggest_drop[1] + 1]:.4f})"
    )

    # ---- 5. Full timeline dump, ~60 rows -----------------------------------------
    print("\n--- Timeline (~60 rows, all channels) ---")
    print(f"{'t(s)':>7}{'current':>9}{'vib_act':>9}{'press':>10}{'temp':>8}{'humid':>8}")
    step = max(1, n // 60)
    for i in range(0, n, step):
        r = rows[i]
        temp_str = "FAIL" if not r["temperature_healthy"] else f"{r['temperature_c']:.1f}"
        hum_str = "FAIL" if not r["humidity_healthy"] else f"{r['humidity_pct']:.1f}"
        print(
            f"{rel_t(r):>7.1f}{cur[i]:>9.4f}{act[i]:>9.2f}{r['pressure_hpa']:>10.2f}"
            f"{temp_str:>8}{hum_str:>8}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
