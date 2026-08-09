# SHTAPM

**Self-Healing Trust-Aware Predictive Maintenance for Adversarially Resilient Industrial IoT.**
Cyber-physical monitoring + autonomous self-healing for a bench water-pump proxy
of a remote pumping station, with a real-time "Aurora" admin dashboard.

Authoritative specs live in [`docs/`](docs/) and [`CLAUDE.md`](CLAUDE.md). Current
build state, decisions, and the phase checklist live in
[`project-state/`](project-state/) — **read those first** for handoff.

## Status
Phase **P0 — Foundations & Spikes**, Milestone 1 (repository foundation).
No application functionality yet. See `project-state/CURRENT_STATE.md`.

## Architecture (non-negotiable)
The edge `sense → detect → attribute → decide → heal → actuate` loop runs entirely
on the Raspberry Pi and **never depends on the backend/cloud/network** (D003).
The backend/dashboard are observe + advisory + audit only. One frozen data
contract is shared across all tiers (D006). Full stack is offline-runnable
(no CDN, self-hosted fonts). Tech stack is frozen by TRD §02.2.

## Layout (TRD §02.6)
```
edge/       Raspberry Pi node — drivers, pipeline, actuation, ledger  (P1–P3)
backend/    FastAPI — MQTT sub, WS gateway, REST, ledger verify        (P4)
frontend/   React + Vite Aurora dashboard                             (P5)
infra/      mosquitto broker config
docs/       authoritative PRD/TRD/AppFlow/UIUX/Schema/ImplPlan
project-state/  implementation memory (state, decisions, log, todo)
```

## Local bring-up (offline four-service stack)
Requires Docker + Docker Compose. Building the frontend image needs the npm
registry once; after images are cached the stack runs offline.
```bash
cp .env.example .env      # then set POSTGRES_PASSWORD (required; no default)
docker compose up         # builds + starts all four services
```
Starts **mosquitto**, **db** (PostgreSQL/TimescaleDB — running but unused by the
app at P0), **backend** (FastAPI), **frontend** (React via nginx).

**Verify:**
- Frontend: open `http://localhost:5173` → the live-telemetry page (shows
  "No telemetry yet…" until a source publishes).
- Backend health: `curl http://localhost:8000/healthz` →
  `{"status":"ok","mqtt_connected":true,...}`.

**Telemetry source (host-side, not a compose service — D008).** The pump edge is
stood in for by the hardware-free simulator; run it on the host to feed live data:
```bash
pip install -r simulator/requirements.txt
PYTHONPATH=backend:. EDGE_MQTT_HOST=localhost EDGE_MQTT_PORT=1883 \
  DEVICE_ID=pump-01 SAMPLE_RATE_HZ=1 python -m simulator
```
The browser connects to the backend WebSocket at `VITE_WS_URL`
(`ws://localhost:8000/ws`, consumed on the host).

**TLS-inspected networks (Zscaler etc.).** If Docker image builds fail with
certificate-verification errors, drop your corporate root CA as a `.crt` into
**both** `backend/certs/` and `frontend/certs/` (gitignored, never committed).
The backend trusts it for pip (`PIP_CERT` → system bundle) and the frontend for
npm (`NODE_EXTRA_CA_CERTS`). Optional and a no-op on normal networks — TLS
verification is never disabled. Export example (macOS):
`security find-certificate -a -p ... > backend/certs/zscaler-root-ca.crt` (copy the same file into `frontend/certs/`).

## Tooling
- Python (edge, backend): ruff + black + pytest — `pip install ".[dev]"`.
- Frontend: Vite + TypeScript + Vitest + ESLint + Prettier (installed in P5).
- Pre-commit: `pip install pre-commit && pre-commit install`.
- CI: `.github/workflows/ci.yml` — Python (ruff/black/pytest) + Frontend
  (typecheck/Vitest/build). Both green as of the CI-repair commit.
