# CURRENT_STATE

> Implementation memory for SHTAPM. A fresh session reads this first, then
> `DECISIONS.md`, `TODO.md`, `IMPLEMENTATION_LOG.md`. Authoritative product spec
> lives in `../CLAUDE.md` and `../docs/` — not duplicated here.

**Last updated:** 2026-08-09

---

## Snapshot
- **Current phase:** P0 — Foundations & Spikes (IN PROGRESS)
- **Current milestone:** P0 Milestone 3.3 — Backend MQTT telemetry ingestion (complete + verified incl. real simulator→Mosquitto→backend path; commit pending approval)
- **Overall completion:** repo + frozen contract + simulator + verified simulator→Mosquitto→backend ingestion done; WS fan-out (M3.4) + React (M3.5) + hardware spikes pending
- **Repository:** github.com/Yeshwanth-lb/SHTAPM (branch `main`; M1 d841404; M2 e1f2e4a; M3.1 0b1c4dd; M3.2 aa1563c pushed; M3.3 uncommitted)

## Completed
- Requirements + design docs authored (`docs/` — PRD, TRD, App Flow, Aurora UI/UX, Backend Schema, Impl Plan).
- `CLAUDE.md` project instructions committed.
- Git repo initialized and pushed to GitHub.
- PRD ↔ Doc06 phase conflict identified and reconciled (see `DECISIONS.md` D001/D002).
- Reconciled implementation roadmap agreed (PRD phase authority; Doc06 = detailed task/test spec mapped into PRD phases).
- Project-state / handoff files created and committed (30b03ee).
- **P0 Milestone 1** (committed d841404) — monorepo skeleton (TRD §02.6); docker-compose (mosquitto+db functional, backend+frontend wired-empty behind `app` profile); `.env.example`; Python + frontend lint/test tooling + CI + pre-commit skeleton; self-hosted font foundation; `.gitignore` hardened; READMEs.
- **P0 Milestone 2** (committed e1f2e4a) — froze the canonical telemetry/decision/ledger contract per **D007** (Doc05 §05.8 authoritative). Pydantic v2 models in `backend/app/schemas/contracts.py`, mirrored TS in `frontend/src/types/contracts.ts`, accept/reject tests.
- **P0 Milestone 3.1** (committed 0b1c4dd) — hardware-free telemetry simulator in top-level `simulator/` (D005/D008): deterministic generator emitting the frozen contract + MQTT publisher to `shtapm/{device_id}/telemetry`. Fixed root pytest wiring so the whole suite runs in one command.
- **P0 Milestone 3.2** (committed aa1563c) — connected simulator → Mosquitto → subscriber verifier. Real round trip verified against `eclipse-mosquitto:2.0`.
- **P0 Milestone 3.3** (uncommitted) — backend MQTT telemetry ingestion: `app/mqtt/consumer.py` (subscribes `shtapm/+/telemetry`, validates frozen contract), `app/services/telemetry_store.py` (in-memory latest-per-device, the seam for M3.4), `app/core/config.py`, `app/main.py` (FastAPI lifespan + `/healthz`). Real simulator→Mosquitto→backend verified. 46/46 with broker; 44 pass + 2 skip without.

## In progress
- P0 Milestone 3.3 verified; awaiting approval to commit/push. M3.4/3.5 not started.

## Next
- **P0 Milestone 3.4** — backend WebSocket fan-out of validated telemetry (reads `TelemetryStore`).
- **M3.5** — minimal React consumer renders live telemetry; then the E2E latency spike/harness.
- Note: integration tests need a broker + paho-mqtt; they self-skip otherwise. Backend runtime now needs fastapi/paho (`backend/requirements.txt`); tests need httpx (dev extra). Docker daemon started to verify; quit Docker Desktop if unwanted.
- P0 gate: clean offline `docker compose up` + go/no-go.
- Hardware spikes (sensor/interface reads, INA219, on-Pi LSTM+IF timing) stay **hardware-blocked** until a Pi/rig is available (`TODO.md`).

## Contract authority (frozen — read before touching any message)
- **D007:** Doc05 §05.8 is authoritative for wire field names/shapes. Full channel names; flat `isolated[]`/`substituted[]`; ledger keeps `payload_hash`; `type` is a WS-envelope concern only (MQTT payloads omit it). Canonical Python = `backend/app/schemas/contracts.py`; TS mirror MUST stay in sync.
- **U14:** `…/command` inject payload is unspecified — do not invent; blocks P4 injection.

## Standing caveats (honest state)
- Fonts (M1): foundation only — woff2 binaries + `@fontsource` pin deferred to P5.
- Local tooling gaps in this env: linters (ruff/black/eslint) and TypeScript are NOT installed; npm is blocked by a TLS/proxy cert error. Python tests run via an isolated venv; ruff/black/eslint/tsc/vitest execute in CI. Do not claim they ran locally.
- `docker compose config` validated; full `docker compose up` on a clean machine not yet run (P0 gate, later milestone).

## Known blockers
Blocking questions are tracked in the roadmap discussion; the ones that gate *code* (not yet resolved — DO NOT silently assume):
- P2: Beta-reputation trust-update formula + recovery dynamics UNDECIDED (weights exist in schema, math does not).
- P2: fault-vs-attack physics/correlation attribution rules + thresholds UNDECIDED.
- P2/P7: SWaT/WADI dataset access UNCONFIRMED (fallback: TEP + bench).
- P3: LSTM — one shared model or two (prognosis vs digital-twin)? UNDECIDED (edge stores single `lstm.pt`).
- P3: digital-twin training-data source UNDECIDED.
- P3: `divergence_threshold` + substitution uncertainty-cap values UNDECIDED (schema column, no default).
- P3: RL reward shaping + acceptable false-isolation rate UNDECIDED.
None of these block P0.

## Hardware availability / dependencies
- Development environment currently has **no Raspberry Pi and no bench rig** attached.
- Hardware-free: P0 scaffolding, P2 (ML on recorded/dataset), P3 (models/logic), P4 (backend), P5 (dashboard), P7 (evaluation).
- Requires Pi + rig: P1 physical acquisition; P3 physical safe-stop / dry-run / <500ms edge timing; P6 live §18.4 run + physical chaos tests.
- Mitigation: telemetry simulator/replay source (D005) stands in for the rig for all non-physical work and is the demo fallback (PRD R1/R2).

## Architecture constraints (non-negotiable)
- Edge safety loop `sense→detect→attribute→decide→heal→actuate` runs entirely on the Pi; **never depends on backend/cloud/network** (D003).
- Backend = read/observe + advisory-control plane only (visualization, history, config, audit, advisory commands). Never in the safety path.
- One **frozen shared data contract** (telemetry/decision/ledger) identical across firmware, simulator, backend, DB, WebSocket, TS types (D006). No component invents field names.
- Ledger = SHA-256 hash chain; Hyperledger is future scope (D004).
- Offline-demo golden rule: whole stack runs on one machine via `docker-compose`, no internet, fonts self-hosted.
- Aurora aesthetic is subordinate to the 1 Hz live stream + <2s sensor→UI + <500ms self-heal budgets; effects auto-downgrade before the data path (TRD §02.9).
- Tech stack frozen by TRD §02.2 (changes require a version bump + a DECISIONS.md entry).
