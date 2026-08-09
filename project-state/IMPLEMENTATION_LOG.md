# IMPLEMENTATION_LOG

> Chronological development log. Append new entries at the bottom after each
> meaningful milestone. Record only work actually done — no fabrication.

---

## 2026-08-09 — Documentation, repo, and planning
- Project documentation prepared in `docs/` (PRD, TRD, App Flow, Aurora UI/UX, Backend Schema, Implementation Plan).
- Git repository initialized.
- `CLAUDE.md` project instructions created and committed.
- Repository pushed to GitHub (github.com/Yeshwanth-lb/SHTAPM, `main` in sync with origin — verified: local HEAD == origin/main @ 725146c).
- PRD ↔ Doc06 phase-numbering conflict identified and reconciled: PRD is authoritative for phase order (D001); Doc06 retained as detailed task/test spec mapped into PRD phases (D002).
- Persistent project-state / handoff system created: `project-state/{CURRENT_STATE,DECISIONS,IMPLEMENTATION_LOG,TODO}.md`.

## 2026-08-09 — P0 Milestone 1: Repository foundation & configuration
- Monorepo directory skeleton created per TRD §02.6 (`edge/`, `backend/`, `frontend/`, `infra/`, `.github/`).
- `docker-compose.yml`: four services. `mosquitto` (eclipse-mosquitto:2.0) + `db` (timescale/timescaledb:2.14.2-pg16) functional; `backend`/`frontend` wired-empty behind an `app` profile so default `up` starts only working infra. Verified with `docker compose config` (valid; default services = db+mosquitto; app profile adds backend+frontend).
- `.env.example` with all TRD §02.7 variables (secrets blank, non-secret dev defaults).
- `infra/mosquitto/mosquitto.conf` foundation (DEV anonymous; P4 hardens per PRD App E).
- Python tooling: root `pyproject.toml` (ruff/black/pytest config + dev group). Placeholder passing tests in `edge/tests` + `backend/tests` (py_compile OK; pytest run deferred to CI — not installed locally).
- Frontend tooling foundation (no app yet): `package.json` (Vite5/TS5.4/Vitest/ESLint/Prettier only), `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`, `eslint.config.js`, `.prettierrc.json`, placeholder Vitest test. JSON validated.
- Self-hosted font FOUNDATION: `src/styles/fonts.css` (@font-face, no CDN) + `src/assets/fonts/FONTS.md` (OFL). woff2 binaries + exact @fontsource pin deferred to P5 — npm package name/version could not be verified in P0 and was not guessed.
- Skeleton `Dockerfile`s for backend/frontend (clearly-labelled placeholders; real images in P4/P5).
- `.pre-commit-config.yaml` (ruff, black, prettier, standard hooks) + `.github/workflows/ci.yml` (Python job real; frontend job gated on the P5 lockfile). YAML validated.
- `.gitignore` extended: model binaries (`edge/models/*.pkl|pt|zip|onnx`), broker runtime state, replay data, logs, ruff/mypy caches. Verified `.DS_Store`, `.env`, `*.pt` are ignored.
- Root `README.md` (offline bring-up, layout, architecture constraints).
- **No application functionality implemented.** No simulator, no MQTT/backend/frontend logic. No Pi spikes faked — recorded hardware-blocked in TODO.

## 2026-08-09 — P0 Milestone 1 committed
- Committed `P0 Milestone 1: repository foundation and configuration` (d841404) and pushed to origin/main.

## 2026-08-09 — P0 Milestone 2: Shared data contract (D006 / D007)
- Resolved the PRD §10.3 ↔ Doc05 §05.8 contract conflict via ruling **D007** (Doc05 §05.8 authoritative; rulings A–E). Recorded in DECISIONS.md.
- Froze the canonical telemetry/decision/ledger contract:
  - `backend/app/schemas/contracts.py` — Pydantic v2 models (`TelemetryMessage`, `DecisionMessage`, `LedgerMessage`, `SensorReadings`, `AnomalyInfo`, `TrustScores`) + enums (`Channel`, `Attribution`, `HealthState`, `RLAction`, `WSFrameType`), `extra="forbid"`, scores constrained [0,1]. Full channel names (A/B), flat `isolated[]`/`substituted[]` (C), ledger keeps `payload_hash` (D), no `type` in MQTT payloads (E).
  - `backend/app/schemas/__init__.py` — exports.
  - `frontend/src/types/contracts.ts` — verbatim TS mirror (interfaces, string-literal unions, WS envelope, typed EXAMPLE_* constants).
- Added `pydantic==2.*` to `backend/requirements.txt` (the contract module needs it; frozen stack). Other backend deps still deferred to P4.
- Tests: `backend/tests/test_contracts.py` (13 cases) + `frontend/src/__tests__/contracts.test.ts` (3 cases).
- Recorded **U14** — the `…/command` inject payload is unspecified in the docs; not invented; blocks P4 injection.
- **Verified (actually ran):** `backend/tests` → 14 passed (13 contract + 1 placeholder), `edge/tests` → 1 passed, in an isolated venv with pydantic 2.13.4 (host has no project deps). **Not run locally:** TS `tsc`/`vitest` — TypeScript could not be installed (npm blocked by TLS/proxy `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`); the TS mirror + test are authored and run in CI/P5.
- No MQTT, simulator, or ML logic implemented. U01–U13 untouched.

## 2026-08-09 — P0 Milestone 2 committed
- Committed `P0 Milestone 2: freeze shared data contract (D006/D007)` (e1f2e4a), pushed to origin/main.

## 2026-08-09 — P0 Milestone 3.1: Telemetry simulator (D005 / D008)
- New top-level `simulator/` package (isolated from `edge/` Pi drivers — D008):
  - `generator.py` — `TelemetrySimulator`: deterministic seeded samples of the six frozen channels; emits the M2 `TelemetryMessage` verbatim (imports the canonical contract; no renamed/invented fields). Caller supplies `ts` → fully reproducible. Baseline means/ranges are simulator-chosen plausible bench values (datasheet-bounded), NOT doc specs.
  - `publisher.py` — `MqttTelemetryPublisher`: publishes to `shtapm/{device_id}/telemetry` at QoS 0 (TRD §02.3); client injected (no hard paho dep → broker-free tests).
  - `__main__.py` — thin 1 Hz CLI runner (builds paho client from env); live broker publish exercised in M3.2+, so not unit-tested.
  - `requirements.txt` (paho-mqtt==1.6.*, pydantic==2.*), `README.md`, tests.
- Test-infra fix (surfaced running the full suite): `backend/tests` + `edge/tests` share `test_placeholder.py`, and root pytest lacked `backend/` on path. Fixed `pyproject.toml`: `pythonpath=["backend","."]`, `addopts=--import-mode=importlib`, added `simulator/tests` to testpaths, added `pydantic==2.*` to the dev extra (contract suite needs it). Now `pytest -q` runs the whole suite from one command (CI-ready).
- **Verified (actually ran):** `pytest -q` (root config, no manual PYTHONPATH) → **27 passed** (13 contract, 2 placeholder, 12 simulator), venv pydantic 2.13.4. Emitted a deterministic example message (seed 1337) — see report.
- Scope kept: no anomaly/trust/ML/decision/ledger/safety, no P1 hardware drivers, no auth/RBAC, no Aurora dashboard. U01–U14 untouched. docs/ + CLAUDE.md untouched.

## 2026-08-09 — P0 Milestone 3.1 committed
- Committed `P0 Milestone 3.1: add hardware-free telemetry simulator` (0b1c4dd), pushed to origin/main.

## 2026-08-09 — P0 Milestone 3.2: MQTT broker integration (D005 path)
- Connected the existing simulator publisher to the project's Mosquitto broker + a subscriber verifier proving: publish → Mosquitto → subscribe → validate against the frozen contract. No FastAPI/WS/DB/ML/hardware.
- New in `simulator/`:
  - `subscriber.py` — `MqttTelemetrySubscriber`: paho-wired (on_connect subscribes `shtapm/{device_id}/telemetry`; on_message validates → `TelemetryMessage`), duck-typed so unit-testable without paho/broker. Reuses `TELEMETRY_TOPIC` from `publisher.py` (no second topic def).
  - `roundtrip.py` — `broker_available()` (stdlib socket check) + `run_roundtrip()` (real pub+sub over the broker; paho imported lazily).
  - `timesource.py` — shared `now_iso_ms()`; `__main__.py` refactored to use it (fixes a latent double-`now()` in the old helper).
  - Tests: `test_subscriber.py` (4 unit, no broker: subscribe, valid collected, bad-JSON + PRD-shorthand recorded as errors not crash); `test_integration_mqtt.py` (real round trip; skips cleanly if no broker / no paho).
- `pyproject.toml`: registered `integration` marker.
- Reused existing config exactly: topic `shtapm/{device_id}/telemetry`, QoS 0, env-driven host/port (no hardcoded secrets), no `type` on MQTT payload, frozen contract unchanged.
- **Verified (actually ran):**
  - `pytest -q` (no broker) → 31 passed, 1 skipped (integration, no broker reachable).
  - Started **real Mosquitto** (`eclipse-mosquitto:2.0`) via `docker compose up -d mosquitto` (had to start the Docker daemon first — it was down; image pulled from the registry), port 1883 open.
  - `pytest -m integration` against it → **1 passed** (real round trip: 3 msgs published→received→validated, order preserved, no `type`).
  - Full suite with broker up → **32 passed**. Broker + volumes then torn down (`docker compose down -v`).
- Side effect: I launched Docker Desktop (daemon) to run the real broker; it is left running (containers/volumes removed). Quit it if unwanted.
- Out of scope / not implemented: status/LWT topic (payload underspecified in docs) — telemetry only. U01–U14 untouched. docs/ + CLAUDE.md untouched.

## Status
- P0 Milestone 3.2 complete and verified (incl. a real Mosquitto round trip); **not yet committed — awaiting approval**.
- Next: P0 Milestone 3.3 — backend MQTT subscriber → WebSocket telemetry fan-out.
