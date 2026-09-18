# SHTAPM

**Self-Healing Trust-Aware Predictive Maintenance for Adversarially Resilient Industrial IoT.**

An edge system that decides whether a misbehaving sensor is a **fault** or an
**attack**, isolates it, and keeps running on a digital-twin reconstruction of the
lost channel — with a tamper-evident audit trail and a real-time dashboard. The
safety loop runs entirely on a Raspberry Pi and never waits on the network.

Authoritative specs live in [`docs/`](docs/) and [`CLAUDE.md`](CLAUDE.md). Build
state, decisions and the phase checklist live in
[`project-state/`](project-state/) — **read `CURRENT_STATE.md` first** for handoff.

---

## Status — 2026-09-18

Running on real hardware: a Raspberry Pi 5 with five physical sensors, streaming
at 1 Hz through MQTT to a FastAPI backend, a database, and a nine-page dashboard.

| Channel | Part | Interface | State |
|---|---|---|---|
| `temperature` | DHT22 | GPIO17 | real |
| `humidity` | DHT22 *(same part)* | GPIO17 | real |
| `vibration` | ADXL335 | MCP3008 / SPI0 | real |
| `pressure` | BMP280 | I²C `0x76` | real |
| `current` | INA219 | I²C `0x40` | real |
| `gas` | — none — | — | **SIMULATED** |

> **`gas` is a synthetic value, not a measurement.** No MQ-135 driver exists. The
> API and dashboard label it `PLACEHOLDER` so it can never be read as real. The
> frozen wire contract carries six plain floats and no provenance marker, so the
> system had to be taught separately which channels are genuine.

**What works end to end:** acquisition → anomaly detection (Isolation Forest) →
per-channel trust scoring → fault-vs-attack attribution → isolation → digital-twin
substitution → MQTT → persistence → REST/WebSocket → dashboard, with substituted
channels rendered as `VIRTUAL`.

**Selected measurements** (all reproducible from `edge/eval/`, evidence in
[`project-state/BENCH_LOAD_VALIDATION.md`](project-state/BENCH_LOAD_VALIDATION.md)):

- 7.18 h continuous capture, 21,799 frames, no inter-frame gap > 5 s
- current ↔ vibration coupling under load: **r = 0.76** (idle rig: R² = 0.019)
- digital twin reconstructs `current` at **45.8 %** skill vs a predict-the-mean baseline
- Isolation Forest on real clean bench data: **0.1 %** false-positive rate

**Deliberately not claimed:** detection rate (needs labelled faults on real
hardware), prognosis accuracy (no pump degradation dataset exists), and any
physical actuation — no relay or GPIO output is wired anywhere in this build.

**Held open on purpose:** the divergence escalation threshold is disabled rather
than guessed. It was measured at a 5.8 % false-escalation rate on clean data, so
the escalate-to-safe-stop path is unreachable by construction until the
reconstruction improves. See `U05` in
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
frontend/        React + Vite dashboard (9 pages)
infra/           mosquitto broker config
docs/            authoritative PRD / TRD / AppFlow / UIUX / Schema / ImplPlan
project-state/   implementation memory (state, decisions, log, todo, evidence)
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
pytest                    # 2,056 passing (edge + backend + simulator)
cd frontend && npm test   # 149 passing
```

Broker- and Postgres-gated integration tests self-skip when those services are
absent. Four tests are `xfail` with recorded reasons — documented limitations, not
unexplained failures.

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
