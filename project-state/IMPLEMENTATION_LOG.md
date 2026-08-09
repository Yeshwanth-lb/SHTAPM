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

## 2026-08-09 — P0 Milestone 3.2 committed
- Committed `P0 Milestone 3.2: integrate telemetry simulator with MQTT broker` (aa1563c), pushed.

## 2026-08-09 — P0 Milestone 3.3: Backend MQTT telemetry ingestion
- Path proven: simulator → Mosquitto → **FastAPI backend** (validate via frozen contract → in-memory store). No DB/auth/WS/REST-history/decisions/ledger/ML.
- New backend modules:
  - `app/core/config.py` — `MqttSettings.from_env()` (MQTT_HOST/PORT; no secrets logged).
  - `app/services/telemetry_store.py` — `TelemetryStore`: thread-safe latest-per-device + count, for M3.4 to read.
  - `app/mqtt/consumer.py` — `TelemetryConsumer`: subscribes `shtapm/+/telemetry`, decodes JSON, validates `TelemetryMessage`, writes store; rejects (counts + logs topic/reason, never payload) malformed JSON, contract violations, wrong topic, topic/payload device mismatch. paho `loop_start` (background thread) = non-blocking; paho imported lazily so `handle` is unit-testable without paho/broker.
  - `app/main.py` — FastAPI app; lifespan starts consumer (`connect_async`+`loop_start`, tolerates broker down) and exposes store/consumer on `app.state`; minimal `/healthz` liveness (no auth, no history).
- Single contract reused (D006/D007) — no second telemetry contract. WS fan-out is M3.4 (store is the seam).
- Deps: `backend/requirements.txt` now activates fastapi==0.110.*, uvicorn==0.29.*, paho-mqtt==1.6.* (+ existing pydantic); DB/auth still deferred to P4. Root dev extra += httpx (TestClient). CI python job now also installs `backend/requirements.txt`.
- Tests added: `test_telemetry_store.py` (3), `test_mqtt_consumer.py` (9: valid/malformed/contract-invalid/extra-field/PRD-shorthand/wrong-topic/device-mismatch/multi-device/topic-parse), `test_app_health.py` (1: /healthz ok with broker down), `test_integration_backend_mqtt.py` (real; skips without broker).
- **Verified (actually ran):**
  - `pytest -q` (no broker) → **44 passed, 2 skipped** (both integration; app-health passed with broker down).
  - Real Mosquitto (`eclipse-mosquitto:2.0`, compose) up → `pytest -m integration` → **2 passed** (backend ingestion + simulator roundtrip); full `pytest -q` → **46 passed**. Broker torn down.
  - Not run locally: ruff/black/eslint/tsc (env lacks them / npm TLS-blocked) → CI. Host warnings from starlette/fastapi on Python 3.14 (`asyncio.iscoroutinefunction` deprecation) are library-internal; CI runs Python 3.11.
- No DECISIONS change (FastAPI lifespan + paho loop_start are standard within the frozen stack; no architectural decision). U01–U14 untouched. docs/ + CLAUDE.md untouched.

## 2026-08-09 — P0 Milestone 3.3 committed
- Committed `P0 Milestone 3.3: add backend MQTT telemetry ingestion` (4c578c5), pushed.

## 2026-08-09 — P0 Milestone 3.4: Backend WebSocket telemetry fan-out
- Full path proven: simulator → Mosquitto → backend consumer → **WebSocket `/ws`** → client. No auth/DB/decision/ledger.
- New backend WS layer (`app/ws/`):
  - `frames.py` — `telemetry_frame(msg)` = `{"type":"telemetry", **msg.model_dump()}` (Doc05 §05.8 flat envelope; ruling E; payload = frozen contract).
  - `broadcaster.py` — `TelemetryBroadcaster`: the seam between the paho thread and asyncio WS clients. `publish_from_thread` → `loop.call_soon_threadsafe` → bounded per-client `asyncio.Queue` (slow client → drop, never block). `subscribe`/`unsubscribe`/`client_count`. P4 can swap for a Redis fan-out without touching the consumer or route.
  - `routes.py` — `/ws` websocket: subscribes to the broadcaster, streams frames, optional `?device_id` filter; `?token=` accepted but NOT enforced (auth = P4); disconnect/errors clean up the subscription.
- Wiring: `consumer.add_sink(...)` (new — ingestion stays decoupled, just calls sinks; sink errors can't break ingestion); `main.py` lifespan creates the broadcaster with the running loop, wires the consumer sink to it, includes the WS router; `/healthz` now reports `ws_clients`.
- Deps: `backend/requirements.txt` += `websockets==12.*` (uvicorn WS protocol for real serving). No new broker/infra (no Redis).
- Tests added: `test_ws_frames.py` (2), `test_broadcaster.py` (4, asyncio via `asyncio.run`, no pytest-asyncio), `test_ws_endpoint.py` (3: broadcast delivery, device filter, healthz ws_clients — TestClient, no broker), `test_integration_ws.py` (real MQTT→backend→WS; skips without broker).
- **Verified (actually ran):**
  - `pytest -q` (no broker) → **53 passed, 3 skipped** (all 3 integration; WS unit + endpoint tests passed without a broker).
  - Real Mosquitto up → `pytest -m integration` → **3 passed** (simulator roundtrip, MQTT→backend ingestion, MQTT→backend→WS); full `pytest -q` → **56 passed**. Broker torn down.
  - Not run locally: ruff/black/eslint/tsc (env lacks them / npm TLS-blocked) → CI. Host warnings = starlette/fastapi asyncio deprecation on Python 3.14 (CI uses 3.11).
- No DECISIONS change (broadcaster/sink seam is standard within the frozen FastAPI+paho stack; no architectural decision, no new infra). U01–U14 untouched. docs/ + CLAUDE.md untouched.

## 2026-08-09 — P0 Milestone 3.4 committed
- Committed `P0 Milestone 3.4: WebSocket telemetry layer` (728838f), pushed.

## 2026-08-09 — P0 Milestone 3.5: React live-telemetry consumer (Option A)
- **M3.5a** React 18.2 scaffold: `index.html`, `src/main.tsx`; Vite react plugin (`@vitejs/plugin-react`); Vitest jsdom + RTL config (`vitest.config.ts`, `src/test/setup.ts`); `tsconfig` jsx + types; `vite-env.d.ts`.
- **M3.5b** `src/hooks/useTelemetryWebSocket.ts` (connects `VITE_WS_URL`, `isTelemetryFrame` guard accepts ONLY frozen-contract telemetry, latest-per-device plain React state — no Zustand, capped-backoff reconnect, `?device_id` filter), `src/features/telemetry/TelemetryView.tsx` (plain six-channel table — no Aurora/Tailwind/charts), `src/App.tsx`, `src/lib/ws.ts`. Reuses `frontend/src/types/contracts.ts` verbatim (no new/renamed fields).
- **M3.5c** `frontend/scripts/ws_smoke.mjs` — dependency-free Node (global WebSocket) live-path client.
- CI: frontend job de-gated (no lockfile locally — npm blocked); now `npm install` → `typecheck` → `test` → `build` (Option A: CI is the RTL/build gate). `backend/requirements.txt` += `websockets==12.*` was added in M3.4.
- **Verified locally (actually ran):**
  - Python full suite (no broker) → **53 passed, 3 skipped** — M3.3/M3.4 intact (frontend files not in pytest scope).
  - **MQTT→backend live under real uvicorn**: started Mosquitto + uvicorn(app) + simulator → `/healthz` showed `mqtt_connected:true, telemetry_count:28` — real simulator→Mosquitto→backend confirmed end-to-end (beyond TestClient).
- **Environment-blocked (NOT verified locally; honest gates):**
  - Real **Backend→WebSocket→external client** under uvicorn: WS upgrade returns **HTTP 403** with both `--ws websockets` and `--ws wsproto` (impl imports fine, `/ws` route registered, HTTP works). App-level WS is proven by the M3.4 Starlette TestClient tests (3 WS tests) + `test_integration_ws`; this is a sandbox uvicorn-WS-serving block (likely localhost `Upgrade` interception by the same gateway that TLS-blocks npm/docker-hub). Node smoke reproduces it here; it will pass against a normally-served backend.
  - Frontend RTL/`tsc`/`vite build`: `npm install` blocked (TLS/proxy; no lockfile generated) → run in CI. package.json version pins unverified locally.
- No DECISIONS change. U01–U14 untouched. docs/ + CLAUDE.md untouched. No Zustand/DB/auth/Redis/Aurora.

## 2026-08-09 — CI fix (Python packaging) + lint debt found
- CI run for M3.5 (`8483283`, run 31326829747): **frontend job PASSED** (typecheck + Vitest/RTL + vite build); **Python job FAILED** at `pip install ".[dev]"` — setuptools flat-layout auto-discovery found 5 top-level dirs ("Multiple top-level packages").
- Fix (packaging only, no functionality change): root `pyproject.toml` now declares an explicit `[build-system]` (setuptools) and opts out of discovery via `[tool.setuptools] py-modules = []` — the root is a tooling/deps umbrella, not a distribution. `.gitignore` += `*.egg-info/` (build artifact).
- Verified in a clean venv via the exact CI path `pip install ".[dev]" -r backend/requirements.txt`: **install succeeds**, `pytest -q` → **53 passed, 3 skipped**.
- **Lint/format pass (approved, style-only, no behavior change):** `ruff check --fix` (import-order I001, pyupgrade UP035/037/038/017, unused-loop B007) + `black .`; plus 6 manual safe fixes — 2× `isinstance(x,(bytes,bytearray))`→`bytes|bytearray` (3.10+/TRD-3.11 OK), 3× long test-JSON wrapped via adjacent string-literal concatenation (identical value, not `# noqa`), 1× dropped an unused `enumerate` index. No lint errors suppressed.
- **CI-equivalent, clean venv (host Python 3.14; CI uses 3.11 — all fixes are ≥3.11-compatible: `X|Y` isinstance, `datetime.UTC`, `collections.abc.Callable`):** `pip install ".[dev]" -r backend/requirements.txt` OK · `ruff check .` **clean** · `black --check .` **clean** · `pytest -q` → **53 passed, 3 skipped**. Python CI job now green end-to-end.
- Frontend untouched (its job already passes).

## 2026-08-09 — CI repair committed + CI green
- Committed `Fix CI: root packaging and Python lint/format checks` (fab702b), pushed. GitHub Actions run 31327554959 for fab702b: **both jobs green** (Python: pip install/ruff/black/pytest ✓; Frontend: typecheck/Vitest/build ✓).

## 2026-08-09 — P0 offline four-service stack
- Goal: `docker compose up` yields a usable offline stack — mosquitto + db + backend + frontend. Simulator stays host-side (D008), NOT a compose service.
- Changes (no app functionality, no contracts/topics, no DB persistence/auth/Redis/ML):
  - `backend/Dockerfile` — real image: `pip install -r requirements.txt` + `CMD uvicorn app.main:app --host [REDACTED_MOCK_PII] --port 8000`.
  - `frontend/Dockerfile` — multi-stage: node build (`npm install` → `npm run build`) → `nginx:alpine` serving `dist/`; `frontend/nginx.conf` (SPA `try_files` fallback).
  - `docker-compose.yml` — removed `profiles:["app"]` (plain `up` starts all four); frontend `5173:80`; header refreshed. db kept running-but-unused (no P4 persistence). Mosquitto unchanged.
  - `README.md` — one-command offline bring-up (`cp .env.example .env` → set `POSTGRES_PASSWORD` → `docker compose up`), verify URLs (`http://localhost:5173`, `http://localhost:8000/healthz`), and host-side simulator command. `POSTGRES_PASSWORD:?` kept (no fake default).
- **Verified locally (actually ran):** `docker compose config` valid (services: backend db frontend mosquitto); `docker compose up mosquitto db` → **db healthy**, mosquitto reachable (1883); backend app (same module/CMD the image runs) via host uvicorn → `/healthz` 200 + `mqtt_connected:true`; **host simulator → compose Mosquitto → backend** ingestion (`telemetry_count` rose to 3, `device pump-01`); `pytest` **56 passed** (broker up → integration ran too). Teardown clean.
- **Environment-blocked (NOT verified here — sandbox TLS/proxy MITMs Docker-build package fetches; base images lack the gateway CA):** backend image build (`pip` cert-verify fail) and frontend image build (`npm` cert-verify fail), therefore full four-service `up` and the browser WebSocket render (the localhost WS-upgrade 403 also persists). NOT worked around — no insecure `--trusted-host`/`strict-ssl=false`/CA hacks added to the images. Builds succeed where TLS isn't intercepted (CI/normal machine); the frontend build already passes in CI (M3.5 frontend job).
- No new DECISION (D008 already scopes the simulator out of compose; the rest is implementation).

## 2026-08-10 — Backend Docker build: optional corporate-CA trust (Zscaler)
- Root cause of the earlier backend image-build failure: the dev network uses Zscaler HTTPS inspection; the Mac trusts the Zscaler root CA but the Docker build's base image does not → `pip` cert-verify fails.
- Fix (build env only; no app/arch/deps change; TLS never disabled; no `--trusted-host`):
  - `backend/Dockerfile`: `COPY certs/ /usr/local/share/ca-certificates/` → `apt-get install ca-certificates` + `update-ca-certificates`, then `ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt` so pip verifies against the SYSTEM bundle (which now includes any dropped-in corporate root) instead of its bundled certifi. Empty `certs/` → no-op on normal networks (standard verification).
  - `backend/certs/.gitkeep` + `.gitignore` (`backend/certs/*` except `.gitkeep`) — corporate certs are drop-in and NEVER committed.
  - `README.md`: how to drop a `.crt` for TLS-inspected networks.
- **Verified (actually ran, with the Zscaler root copied into backend/certs/ locally, gitignored):** `docker compose config` valid; `docker compose build backend` **succeeds** (pip installs fastapi/uvicorn/paho/pydantic/websockets inside the image); `docker run shtapm-backend python -c "import fastapi,uvicorn,paho.mqtt.client,pydantic,websockets"` → OK; `pytest -q` → 56 passed. First build attempt (system trust only, no PIP_CERT) still failed → confirmed pip needs `PIP_CERT`; second build passed.
- **Not confirmed (out of scope — separate finding):** the backend *container* run — it starts uvicorn then logs `ERROR: [Errno -2] Name or service not known` (MQTT host DNS) and exits. Appears to be sandbox Docker-DNS resolving `mosquitto` + a graceful-degradation gap (an unresolvable MQTT host aborts startup rather than degrading). NOT fixed here (this task is the build env only; no app changes). Needs a separate app-scope fix/investigation. App runs fine when the MQTT host resolves (host-uvicorn `/healthz` + ingestion verified previously; TestClient tests pass). Also: repeated Docker daemon instability in the sandbox (stale docker-proxy holding host :8000, daemon crashes on kill) hampered container runtime checks.

## Status
- P0 offline stack implemented + partially verified. Backend image now BUILDS behind Zscaler (CA drop-in). Image builds + browser render otherwise close out on CI / a normal machine.
- Open finding (separate task): backend container exits on unresolvable MQTT host DNS (graceful-degradation gap + sandbox Docker-DNS). Frontend image build still needs the same CA drop-in pattern (not done — backend-only per this task).
- Not yet committed — awaiting approval.
- Next: (approved) address container MQTT-host DNS/graceful-startup; frontend CA drop-in; E2E latency spike; P0 gate close-out on a normal machine.
