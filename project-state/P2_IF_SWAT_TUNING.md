# P2 — Isolation Forest flag-threshold tuning (SWaT.A1, real full-dataset run)

**Date:** 2026-09-13
**Status:** SWaT-domain diagnostic evidence for `edge/main.py`'s
`_P2_DETECTOR_FLAG_THRESHOLD`. NOT a P2 acceptance result, NOT a bench
calibration — see the "what this is / is not" note at the end.

## What was run

`edge/eval/swat_eval.py`'s harness (D011/D012 methodology, six-tag proxy
mapping, fit-only-on-`Normal_v1` no-leakage discipline) was actually
executed end to end against the real, full dataset — not the module's own
`--limit`-truncated fast path:

- `SWaT_Dataset_Normal_v1.xlsx`: 495,000 rows
- `SWaT_Dataset_Attack_v0.xlsx`: 449,919 rows, 35 separate contiguous
  labelled attack events
- 16,500 windows fit `IsolationForestDetector` + `ConsistencyProvider` +
  `SeverityThresholdFlagPolicy` (Normal_v1 only)
- 14,997 evaluation windows scored (1,856 attack-labeled, 13,141
  normal-labeled), from one continuous `P2Pipeline.process()` call spanning
  Normal_v1 immediately followed by Attack_v0 (so h/k/trust state warms up
  naturally before the labelled-attack region, per the harness's own design)

## Result 1 — window-level threshold sweep

All thresholds evaluated from ONE pipeline pass (severity recorded once per
window, thresholds swept post hoc — not 20 separate pipeline runs):

| threshold | TP | FP | TN | FN | detection_rate | fp_rate | F1 |
|---|---|---|---|---|---|---|---|
| 0.80 | 1232 | 3260 | 9881 | 624 | 0.664 | 0.248 | 0.388 |
| 0.85 | 1098 | 2471 | 10670 | 758 | 0.592 | 0.188 | 0.405 |
| **0.90** | **916** | **1611** | **11530** | **940** | **0.494** | **0.123** | **0.418** |
| 0.95 | 616 | 859 | 12282 | 1240 | 0.332 | 0.065 | 0.370 |
| 0.99 | 231 | 173 | 12968 | 1625 | 0.124 | 0.013 | 0.204 |

(Full 0.80–0.99 sweep at 0.01 steps was computed; this table shows the
chosen point and four others for context.)

**Chosen: threshold = 0.90 (best F1 across the full sweep).**

## Result 2 — event-level (O2-style) onset-detection latency at threshold=0.90

Window-level accuracy above is a harsh metric (every 30-sample slice of an
attack must be individually flagged). The PRD's own O2 framing is event-level
— was each attack noticed at all, and how fast:

- **Attack onsets ever flagged at least once: 34 / 35 (97%)**
- Never flagged (honest miss): 1 / 35
- Caught within 1 window (immediate): 12
- **Caught within the PRD's ≤3-window target: 16 / 35 (46%)**
- Latency to first flag (windows): mean 7.29, median 4.00, max 29
- Raw per-onset latencies: `[28, 4, 3, 3, 7, 13, 1, 24, 5, 1, 6, 25, 10, 1, 7, 1, 12, 1, 4, 1, 13, 1, 10, 1, 1, 16, 2, 1, 1, 2, 7, 6, 29, 1]`

## Reading

Almost every real attack is eventually noticed (97%); the honest weak point
is speed, not blindness — under half meet the strict ≤3-window bar, and the
slowest took ~15 minutes to first flag. A lower threshold (e.g. 0.80) trades
faster/more detection for a higher false-alarm rate (24.8% vs 12.3%) — a
real, quantified dial, not a guess.

## What this is — and is NOT

- **Is:** real evidence a raw, single, untuned Isolation Forest detector
  behaves reasonably against real labelled attacks, once given a real
  (rather than placeholder) threshold. Legitimate to cite for the project
  write-up's O10-style evaluation.
- **Is NOT:** a claim about accuracy on this project's actual bench sensors.
  SWaT's six tags are relabeled onto our channel names as a plumbing/proxy
  substitution only (D011/D012) — no physical equivalence is claimed for
  any of them. `AIT402` (mapped to `gas`) is aqueous ORP, never an
  ambient-gas reading.
- **Is NOT** an attribution/O3 result — `k` and `AttributionEngine` are
  excluded from every SWaT report per D011 C/D (current/vibration, and any
  concrete PhysicsRule validation, are both structurally absent from SWaT).
- **Is NOT** the model deployed on the Pi. `IsolationForestDetector` is
  re-fit fresh, live, on the Pi's own real clean windows at every process
  start (`LiveP2Monitor`'s `additional_fit_targets` bootstrap, same
  mechanism `ConsistencyProvider` already used) — the SWaT-fitted model
  itself is never reused. Only the threshold value (0.90, a percentile-style
  cutoff, which travels better than a raw score would) carries over as a
  starting point, per `edge/main.py`'s own comment. Must be revisited once
  real bench clean/faulty/spoofed data exists (U07).

## Reproducing

The two ad-hoc scripts used to produce these numbers were session-scratchpad
files, not committed to this repo (consistent with the dataset itself never
being committed — see `edge/eval/swat_eval.py`'s own docstring). To
reproduce: run `edge/eval/swat_eval.py` (or an equivalent sweep over its
`fit_baseline`/`build_pipeline` functions) against a local, gitignored
`datasets/SWaT_Dataset_{Normal_v1,Attack_v0}.xlsx` pair. Full run time on
this dev machine: ~26 minutes per pass (dominated by `openpyxl` xlsx row
reads, not the ML itself).
