# CURRENT_STATE

> Implementation memory for SHTAPM. A fresh session reads this first, then
> `DECISIONS.md`, `TODO.md`, `IMPLEMENTATION_LOG.md`. Authoritative product spec
> lives in `../CLAUDE.md` and `../docs/` — not duplicated here.

**Last updated:** 2026-08-09

---

## Snapshot
- **Current phase:** P0 — Foundations & Spikes (IN PROGRESS)
- **Current milestone:** P0 Milestone 1 — Repository foundation & configuration (complete + verified; commit pending approval)
- **Overall completion:** repo scaffolding done; still ~0% application functionality
- **Repository:** github.com/Yeshwanth-lb/SHTAPM (branch `main`, in sync with origin @ 30b03ee)

## Completed
- Requirements + design docs authored (`docs/` — PRD, TRD, App Flow, Aurora UI/UX, Backend Schema, Impl Plan).
- `CLAUDE.md` project instructions committed.
- Git repo initialized and pushed to GitHub.
- PRD ↔ Doc06 phase conflict identified and reconciled (see `DECISIONS.md` D001/D002).
- Reconciled implementation roadmap agreed (PRD phase authority; Doc06 = detailed task/test spec mapped into PRD phases).
- Project-state / handoff files created and committed (30b03ee).
- **P0 Milestone 1** — monorepo skeleton (TRD §02.6); docker-compose (mosquitto+db functional, backend+frontend wired-empty behind `app` profile); `.env.example` (all §02.7 vars); Python + frontend lint/test tooling + CI + pre-commit skeleton; self-hosted font foundation; `.gitignore` hardened; READMEs. Verified: compose config valid, JSON/YAML valid, python compiles, ignore rules correct. No application logic, no faked hardware.

## In progress
- P0 Milestone 1 verified; awaiting approval to commit/push. Nothing else started.

## Next
- **P0 Milestone 2** — freeze the shared data-contract stub (telemetry/decision/ledger; D006).
- Then hardware-free telemetry **simulator/replay** scaffold (D005) and the software MQTT→backend→WS→React latency spike + harness.
- Remaining P0 hardware spikes (sensor/interface reads, INA219, on-Pi LSTM+IF timing) stay **hardware-blocked** until a Pi/rig is available (see `TODO.md`).

## Milestone-1 caveats (honest state)
- Fonts: foundation only — woff2 binaries + exact vendoring pin deferred to P5 (npm package unverifiable in P0; not guessed).
- Linters (ruff/black/eslint) configured but NOT executed locally (not installed here) — they run in CI.
- `docker compose config` validated; a full `docker compose up` on a clean machine has not been run yet (that is the P0 gate, a later milestone).

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
