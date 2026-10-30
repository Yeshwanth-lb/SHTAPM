# SHTAPM — Handover (read this first)

Written 2026-10-30, the last day of the previous Claude Code subscription, so that
a new session (or a new teammate) can resume with full context. If this file and
another document disagree, this file is the newer one; the deeper records are
`project-state/DECISIONS.md` (every engineering decision, D001–D060) and
`project-state/CURRENT_STATE.md`.

## 1. What the project is

**Self-Healing Trust-Aware Predictive Maintenance System (SHTAPM)** — an edge system
for an industrial pump (bench scale: a 130-size DC motor) that decides whether an
anomalous sensor reading is a **fault** or an **attack**, isolates the untrusted
channel, keeps monitoring on an LSTM digital-twin reconstruction, stops the pump
safely when trust cannot be restored, and records every safety-relevant decision
in a SHA-256 hash-chained ledger. Raspberry Pi 5 edge → MQTT → FastAPI backend →
React dashboard.

Team: Durgashree R (1BM23IC023), Keerthi S (1BM23IC033), Yeshwanth L B
(1BM23IC070). Guide: Prof. Tejashwini A G, Assistant Professor, Dept. of CSE(ICB),
B.M.S. College of Engineering, Bengaluru. Major Project Phase-2 (23IC7PWPP2),
academic year 2026–2027.

## 2. Where things are

| Thing | Location |
|---|---|
| **Real working clone (use this one)** | `C:\Users\Yeshwanth L B\mpp2\SHTAPM` |
| Stale clone (do not use) | `C:\Users\Yeshwanth L B\Projects\SHTAPM` (Claude Code's old cwd) |
| Pi | `ssh shtapm@shtapm-pi.local` (fallback: `hostname -I` on the Pi); repo `~/SHTAPM`, venv `.venv`, systemd service `shtapm` (env file `~/SHTAPM/.env`) |
| Remote | `https://github.com/Yeshwanth-lb/SHTAPM`, branch `main` (a local `ui-polish` worktree exists at `..\SHTAPM-ui`; the premium UI is already merged) |
| Specs (source of truth) | `docs/` and `CLAUDE.md` |
| Decisions / evidence | `project-state/DECISIONS.md`, `EVALUATION_RESULTS_2026-10-26.md`, `DEMO_RUNBOOK.md`, `DEMO_CARD.md` |
| **Command book** (start, sensors, demo, baseline, replay, fixes) | `COMMANDS.md` |
| **Final test report** | `project-state/TEST_REPORT_2026-10-30.md` |
| Report (89 pages) | `report/` → `pdflatex main.tex` ×3 |
| Conference paper (IEEE, 6 pages) | `paper/` |
| Journal paper (28 pages) | `paper_journal/` (bibliography is `bib.tex`) |

Gitignored on purpose (they exist only on the laptop/Pi): `models/` (twin bundle,
P2 baseline), `*capture*.jsonl`, `final_baseline.jsonl`, `results/`, `datasets/`
(SWaT is access-restricted), `.env`. Copy models to the Pi with `scp`; the loader
takes the alphabetically first top-level `models/*.json` twin, so keep backups in
`models/prev/`.

## 3. How to run it

Pi (SSH window):
```
sudo systemctl start mosquitto
sudo systemctl start shtapm
systemctl status shtapm.service        # want: active (running)
```
Laptop, two PowerShell windows:
```
cd "C:\Users\Yeshwanth L B\mpp2\SHTAPM\backend"
python -m uvicorn app.main:app --port 8002 --env-file ../.env

cd "C:\Users\Yeshwanth L B\mpp2\SHTAPM\frontend"
npm run dev                            # open http://localhost:5173
```
Never run `npm install` (it rewrites the protected `package-lock.json`). Laptop and
Pi must be on the same hotspot. Health: `curl http://localhost:8002/healthz`.
Hardware-free: the simulator or the Pi's recorded-session fallback
(`EDGE_SOURCE=replay`, D040). Full procedure and troubleshooting:
`project-state/DEMO_RUNBOOK.md`. The demo scenarios (Device page → Scenario
injection) are in `project-state/DEMO_CARD.md`.

## 4. Current state (2026-10-30)

**Done and verified**
- Real hardware: DHT22 (temp+humidity), ADXL335+MCP3008 (vibration), BMP280
  (pressure), INA219 (current). 1 Hz, six-channel frozen contract.
- Edge pipeline: preprocessing → Isolation Forest (flag at severity 0.90) →
  Beta trust (g = 0.4c + 0.3k + 0.3h, λ = 0.7, bands 0.7/0.4) → operating-state
  attribution (current vs vibration) → isolation → LSTM twin substitution (60 s
  budget) → latched Safe Pump-Stop → hash-chained ledger → alerts.
- Final 51.4-minute baseline recorded; learned vibration bands idle ≤ 0.142 g,
  running ≥ 0.314 g (D049). Results: 0 false attacks on 2,552 clean
  channel-windows; 73 % of state-crossing attacks and 85 % of faults attributed
  correctly (balanced accuracy 79 % vs 60 % for the old trend-sign rule); twin
  cuts served-value error 79–87 % out of sample.
- Live-verified: constant spoof → ATTACK in ~23 s, bias → ATTACK in ~19 s, stuck
  current → FAULT, Safe Pump-Stop exactly 60 s after isolation, ledger "Chain
  intact".
- Dashboard: ISA-101 control room with premium finish (D052–D060): sensor detail
  drawer, incident timeline, alert toasts, live architecture view, decisions
  timeline. **The "mission control" redesign was rejected by the user and
  reverted — do not redo a whole-look change without showing a mock and getting
  a yes first.** The demo-scenarios box was removed on purpose (it showed only 3
  attack types).
- Report, IEEE paper and journal paper written; tests and lint recorded in
  `project-state/TEST_REPORT_2026-10-30.md`.

**Honest limits (keep them stated this way everywhere)**
- `gas` is **simulated**: the MQ-135 driver and signal path are implemented and
  tested (D044) but the sensor is not wired. Switching to the real sensor needs
  the wiring in `DEMO_RUNBOOK.md` and a **new baseline recording**.
- The pump relay is **software-verified only** (in-memory relay); no physical
  relay is wired. Wiring steps are in `DEMO_RUNBOOK.md` (GPIO27, normally-open).
- The load is a small DC motor, not a pump, so dry-run protection was verified on
  injected frames.
- Within-state attacks (a falsified reading that stays in its true motor state)
  and drift-vs-ramp cannot be separated by physics on this rig (0/23). This is a
  documented physical limit (EVALUATION_RESULTS §8), not a bug.
- RUL prognosis and the DQN response policy exist as tested modules but are not
  deployed (no pump run-to-failure data; reward weights are open decision U06).
  Divergence-based escalation is disabled on purpose (U05).
- Report/paper wording rules agreed with the user: present the full system as
  designed and implemented, describe gas/relay accurately as above, never invent
  measurements, RUL is future work. Do not claim hardware that was not used.

**Remaining / optional**
1. Add the Turnitin + AI-content report pages to report Appendix B (library
   provides them); update Appendix A with the real venue once a paper is submitted.
2. Choose a publication venue and re-flow the paper into its template/page limit.
3. Run Turnitin on the report **before** the paper is public.
4. Optional hardware: wire MQ-135 and/or the relay, re-record a baseline
   (`edge/scripts/load_capture.py`, check with `scripts/capture_check.py` at
   minute 5), re-run `scripts/final_eval.py`, then update results.
5. Optional: broker authentication + TLS, PostgreSQL/TimescaleDB migration,
   physical pump validation.

## 5. Working rules and user preferences

- Follow `CLAUDE.md`: read the docs first, explain the plan, implement only the
  requested scope, do not jump phases, log decisions in `DECISIONS.md` (next
  number is **D061** — D061 was used once for the reverted redesign and removed).
- Give the user numbered steps with exact copy-paste commands, state which window
  (Pi SSH vs laptop PowerShell), never use placeholders like `<pi-ip>`, say what
  output to expect. Verify every real sensor before any recording. Keep motor runs
  short (it overheats); long recordings via `setsid nohup`.
- Report negative results honestly. The user asked more than once to present
  simulated parts as real; that was declined, and the documents were written
  honestly instead. Keep it that way.
- The teacher is a top UI/UX designer: purposeful motion, consistency across all
  pages; demo reliability always outranks looks.
- Python tests need `PYTHONPATH="backend;."` set (handled by `pyproject.toml`'s
  pytest config when run from the repo root). Do not run heavy evals in parallel
  with the full test suite (it looks hung).

## 6. Useful commands

```
python -m pytest -q                         # all Python tests (~10 min)
cd frontend && npx vitest run && npx tsc --noEmit && npx eslint .
python -m ruff check . && python -m black --check edge backend simulator scripts
python scripts/final_eval.py final_baseline.jsonl   # bench evaluation → results/
python scripts/preflight.py                         # T-15 min self-check
cd report && pdflatex main.tex                      # run 3 times (MiKTeX is installed)
```
MiKTeX lives at `%LOCALAPPDATA%\Programs\MiKTeX\miktex\bin\x64`; auto-install of
missing LaTeX packages is on.
