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

## Local bring-up (offline)
Requires Docker + Docker Compose. Images must be cached locally for a truly
offline demo.
```bash
cp .env.example .env      # then set POSTGRES_PASSWORD and JWT_SECRET_KEY
docker compose up         # starts mosquitto + db (functional infra)
```
`backend` and `frontend` are **wired-empty** in P0 and gated behind the `app`
profile (`docker compose --profile app up`) — they gain real applications in
P4 / P5. Do not expect them to serve anything yet.

## Tooling
- Python (edge, backend): ruff + black + pytest — `pip install ".[dev]"`.
- Frontend: Vite + TypeScript + Vitest + ESLint + Prettier (installed in P5).
- Pre-commit: `pip install pre-commit && pre-commit install`.
- CI: `.github/workflows/ci.yml` (Python now; frontend job activates once the
  P5 lockfile exists).
