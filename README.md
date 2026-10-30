# SHTAPM

**Self-Healing Trust-Aware Predictive Maintenance for Adversarially Resilient Industrial IoT.**

An edge system that decides whether a misbehaving sensor is a **fault** or an
**attack**, isolates it, and keeps running on a digital-twin reconstruction of the
lost channel — with a tamper-evident audit trail and a real-time dashboard. The
safety loop runs entirely on a Raspberry Pi and never waits on the network.

Authoritative specs live in [`docs/`](docs/) and [`CLAUDE.md`](CLAUDE.md). Build
state, decisions and the phase checklist live in
[`project-state/`](project-state/). **Starting a new session (human or Claude
Code)? Read [`HANDOVER.md`](HANDOVER.md) first** — it is the single entry point
with the current state, how to run everything, and what is left.

---

## Status — 2026-10-30

Major Project Phase-2 is complete. Running on real hardware: a Raspberry Pi 5
with five physical sensors, streaming at 1 Hz through MQTT to a FastAPI backend,
a database, and a premium industrial-HMI dashboard (login, control room, sensor
detail, device, decisions, history, alerts, ledger, system, users, settings).

**Deliverables in this repository**

| Folder | What it is |
|---|---|
| [`report/`](report/) | The 89-page final project report (LaTeX, college template) |
| [`paper/`](paper/) | 6-page IEEE conference-format paper |
| [`paper_journal/`](paper_journal/) | 28-page journal-format paper (single column, section-numbered) |
| [`project-state/TEST_REPORT_2026-10-30.md`](project-state/TEST_REPORT_2026-10-30.md) | The single final test report |

Build any of them with `pdflatex main.tex` (three passes) inside its folder. The
report and the papers use their own `figures/` and `data/` folders.

| Channel | Part | Interface | State |
|---|---|---|---|
| `temperature` | DHT22 | GPIO17 | real |
| `humidity` | DHT22 *(same part)* | GPIO17 | real |
| `vibration` | ADXL335 | MCP3008 / SPI0 | real |
| `pressure` | BMP280 | I²C `0x76` | real |
| `current` | INA219 | I²C `0x40` | real |
| `gas` | — none — | — | **SIMULATED** |

> **`gas` is a synthetic value, not a measurement.** The MQ-135 driver and its
> voltage-divider signal path are implemented and unit-tested (D044), but the
> sensor is not wired, so the experiments use the configurable emulated source.
> The API and dashboard label it `PLACEHOLDER` so it can never be read as real. The
> frozen wire contract carries six plain floats and no provenance marker, so the
> system had to be taught separately which channels are genuine.
>
> **The pump relay is software-verified only.** The safety supervisor (latched
> Safe Pump-Stop after 60 s of substitution, 10 s watchdog, dry-run rule) is
> implemented and tested against an in-memory relay; no physical relay is wired.

**What works end to end:** acquisition → anomaly detection (Isolation Forest) →
per-channel trust scoring → fault-vs-attack attribution → isolation → digital-twin
substitution → MQTT → persistence → REST/WebSocket → dashboard, with substituted
channels rendered as `VIRTUAL`.

**Headline results** (final 51.4-minute real-hardware baseline, 2026-10-28;
reproducible with `python scripts/final_eval.py final_baseline.jsonl`; full
evidence in
[`project-state/EVALUATION_RESULTS_2026-10-26.md`](project-state/EVALUATION_RESULTS_2026-10-26.md)):

- **0 false attack attributions on 2,552 clean channel-windows**
- state-crossing attacks attributed: **73 %** (32/44); faults kept as faults:
  **85 %** (23/27); balanced accuracy **79 %** vs **60 %** for the old trend-sign rule
- digital twin cuts the served-value error under attack by **79–87 %** out of
  sample (0.60 A → 0.079 / 0.12 A); held-out skill **+47.3 %**
- live system: spoof attributed as ATTACK in 23 s, bias in 19 s; latched
  Safe Pump-Stop exactly 60 s after isolation; ledger verified intact (200 blocks)
- SWaT.A1 detection and a 7.2 h idle recording are reported in the paper and report

**Stated limits (not hidden):** attacks that keep a reading inside its true
physical state (0/23) and drift-vs-ramp are indistinguishable from clean data on
this rig. Remaining-useful-life prognosis and the DQN response policy exist as
tested modules but are **not deployed** (no pump run-to-failure data; reward
weights are an open policy decision, `U06`).

**Held open on purpose:** the divergence escalation threshold is disabled rather
than guessed. On clean held-out data a 3σ threshold would false-escalate in 4.5 %
of windows, so escalation by divergence is off; the 60 s substitution budget
still stops the pump. See `U05` in
[`project-state/DECISIONS.md`](project-state/DECISIONS.md).

---

## Architecture (non-negotiable)

The edge `sense → detect → attribute → decide → heal → actuate` loop runs entirely
on the Raspberry Pi and **never depends on the backend/cloud/network** (D003). The
backend and dashboard are observe + advisory + audit only. One frozen data contract
is shared across all tiers (D006/D007). The full stack is offline-runnable (no CDN,
self-hosted fonts). The tech stack is frozen by TRD §02.2.

```
edge/            Raspberry Pi node — drivers, P2 pipeline, self-healing, RL scaffolding
backend/         FastAPI — MQTT consumers, WS gateway, REST, auth, ledger
frontend/        React + Vite dashboard (11 pages, ISA-101 industrial HMI)
infra/           mosquitto broker config
docs/            authoritative PRD / TRD / AppFlow / UIUX / Schema / ImplPlan
project-state/   implementation memory (state, decisions, log, todo, evidence, test report)
report/          final project report (LaTeX)
paper/           IEEE conference-format paper (LaTeX)
paper_journal/   journal-format paper (LaTeX)
HANDOVER.md      start here when resuming work
```

---

## Running it

### With the real bench (Raspberry Pi)

On the Pi, with the sensors wired and a virtualenv that has the Adafruit libraries:

```bash
sudo systemctl start mosquitto
PYTHONPATH=backend:. .venv/bin/python edge/main.py     # or: systemctl start shtapm
```

Confirm frames are publishing:

```bash
mosquitto_sub -h localhost -t 'shtapm/pump-01/telemetry' -C 5 -v
```

**Self-healing needs a trained twin.** It is not committed — a twin is an artifact
of one specific bench capture, and captures are gitignored evidence. Train one from
a capture taken with `edge/scripts/load_capture.py`:

```bash
PYTHONPATH=backend:. .venv/bin/python -m edge.eval.bench_twin_training \
    motor_load_full.jsonl --epochs 40 --targets current --save-prefix models/twin
```

Without a bundle, substitution is simply unavailable and logged once — telemetry,
detection and trust scoring all continue. A missing model never stops the pipeline.

**Bench tooling** (diagnostics, not production): `edge/scripts/hw_diagnostic.py`
tests every sensor individually; `edge/scripts/load_capture.py` records a capture.
Both require the venv interpreter and that `shtapm.service` be stopped first — the
DHT22's GPIO protocol has no bus arbitration, so two readers corrupt each other.

### Without hardware (simulator)

```bash
cp .env.example .env      # then set POSTGRES_PASSWORD (required; no default)
docker compose up         # mosquitto, db, backend, frontend
```

Then feed it from the hardware-free simulator, which runs host-side rather than as
a compose service (D008):

```bash
pip install -r simulator/requirements.txt
PYTHONPATH=backend:. EDGE_MQTT_HOST=localhost EDGE_MQTT_PORT=1883 \
  DEVICE_ID=pump-01 SAMPLE_RATE_HZ=1 python -m simulator
```

**Verify:** dashboard at `http://localhost:5173`; backend health at
`curl http://localhost:8002/healthz` → `{"status":"ok","mqtt_connected":true,...}`.

### Backend against a live Pi, without Docker

Point `MQTT_HOST` at the Pi's IP in `.env`, then:

```bash
pip install uvicorn python-dotenv
cd backend && python -m uvicorn app.main:app --port 8002 --env-file ../.env
PYTHONPATH=backend python -m app.core.seed   # admin user + sensor registry
cd frontend && npm run dev
```

The sensor registry seed matters: the API reports a channel as `live` only when the
declaration (`SHTAPM_CHANNEL_SOURCES`) **and** the registry agree.

---

## Tests

```bash
pytest                    # 2,358 passing, 0 failed (edge + backend + simulator)
cd frontend && npm test   # 259 passing, 0 failed
```

Broker- and Postgres-gated integration tests self-skip when those services are
absent. Eight DHT22 tests are Linux-only (Windows forbids `:` in file names) and
four are `xfail` with recorded reasons — documented limitations, not unexplained
failures. The full results, lint, hardware scenarios and document builds are in
[`project-state/TEST_REPORT_2026-10-30.md`](project-state/TEST_REPORT_2026-10-30.md).

Day-to-day commands (start everything, check every sensor, demo scenarios,
baseline recording, replay fallback, troubleshooting) are in
[`COMMANDS.md`](COMMANDS.md).

---

## Tooling

- Python: `ruff` + `black` + `pytest` — `pip install ".[dev]"`
- Frontend: Vite + TypeScript + Vitest + ESLint + Prettier
- Pre-commit: `pip install pre-commit && pre-commit install`
- CI: `.github/workflows/ci.yml` — Python (ruff/black/pytest) and frontend
  (typecheck/Vitest/build)

**TLS-inspected networks (Zscaler etc.).** If Docker image builds fail with
certificate-verification errors, drop your corporate root CA as a `.crt` into both
`backend/certs/` and `frontend/certs/` (gitignored, never committed). The backend
trusts it for pip (`PIP_CERT`), the frontend for npm (`NODE_EXTRA_CA_CERTS`).
Optional, a no-op on normal networks, and TLS verification is never disabled.
