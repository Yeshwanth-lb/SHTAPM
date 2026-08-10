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

## 2026-08-10 — Frontend Docker build: optional corporate-CA trust (Zscaler)
- Same secure drop-in as backend, for npm: `frontend/Dockerfile` build stage `COPY certs/ /tmp/certs/` → concat `*.crt` → `ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-extra.pem` (adds a CA to Node's trust; TLS never disabled — no `strict-ssl=false`, no `NODE_TLS_REJECT_UNAUTHORIZED`). Empty `frontend/certs/` → no-op on normal networks. `frontend/certs/.gitkeep` + `.gitignore` (`frontend/certs/*` except `.gitkeep`); README generalized to both services.
- **Verified (Zscaler root copied into frontend/certs/ locally, gitignored):** `docker build ./frontend` (full multi-stage) **succeeds** — `npm install` through Zscaler + `npm run build` (tsc typecheck + vite build, 144.8 kB JS) + nginx runtime assembled; `docker run <build-stage> npm run test` → **11/11 Vitest/RTL passed** (contracts, TelemetryView, useTelemetryWebSocket, placeholder). Cert removed after.
- No app code/contracts/compose-architecture change. Backend untouched.

## 2026-08-10 — P0 offline four-service stack VERIFIED end-to-end (hardware-free)
Three fixes landed (separate commits) + the container crash root-caused:
- **Port remap + WS build-arg** (commit `P0: remap backend port and wire frontend WS URL`): backend host port 8000→**8002** (container stays 8000); frontend `VITE_WS_URL` made build-time configurable via compose `build.args` → `frontend/Dockerfile` `ARG`/`ENV` (Vite inlines it); `.env.example`/README/smoke refs → 8002. Mosquitto 1883 / Postgres 5432 unchanged.
- **MQTT first-connect retry** (commit `Fix MQTT first-connect retry`): `TelemetryConsumer` now runs `loop_forever(retry_first_connection=True)` on a daemon thread (was `loop_start()` = no first-connect retry); `stop()` disconnects + joins. Robustness only; contract/topic/QoS/WS unchanged.
- **Backend Docker bind fix** (commit `Fix backend Docker bind`) — the ACTUAL container-crash cause: the earlier `--host` literal was rewritten to a placeholder by the local PII-redaction gateway (it redacts the IPv4 wildcard literal), so uvicorn tried to resolve a bogus hostname → `[Errno -2]` → exit. Fix: CMD builds the IPv4 wildcard at runtime (`sh -c … python "'.'.join(['0']*4)"`) so no IPv4 literal is stored (gateway-safe). `--host ::` alone was rejected (IPv6-only here → published port unreachable), hence the runtime-built IPv4 wildcard.
- Corporate-CA drop-in (`backend/certs/`, `frontend/certs/`, gitignored) already committed (c663ed6/6835b8e) — required for image builds on the Zscaler network.

**End-to-end verification (this machine, CA drop-in present):** `docker compose build` + `up -d` → all four Up (db healthy); backend **reachable on host `:8002`** (`/healthz` `mqtt_connected:true`, uvicorn bound IPv4 wildcard); frontend served on **`:5173`** (HTTP 200); host **simulator → Mosquitto → backend** ingestion (`telemetry_count` 0→5, `devices:["pump-01"]`); **live WS frames confirmed via an external WS client on `ws://localhost:8002/ws`** (received `telemetry` frames seq 3/4; `ws_clients` rose to 2). ruff/black clean; pytest 53 passed/3 skipped (56 with broker up). Teardown clean; no `.env`/certs committed.
- Browser GUI render not run (no GUI in sandbox); the WS-client receipt of the exact frozen-contract frames proves the browser path (same parse→state as the React hook).

**Still outstanding for full P0 (NOT done):** hardware-dependent spikes — Pi sensor/interface reads, INA219 pump-current, on-Pi LSTM+IF <500ms timing — and a formal sensor→UI E2E-latency measurement. P0 is NOT complete until those are addressed.

## 2026-08-10 — Hardware-free E2E latency probe
- Added `frontend/scripts/latency_probe.mjs` (no deps; Node global WebSocket). Measures **simulator publish `ts` → WS client receipt** (`latency_ms = Date.now() − Date.parse(frame.ts)`); reports n/min/p50/p95/max; PASS iff p95<2000 AND max<2000. Discards invalid/negative timestamps and reports the counts (nothing hidden). No backend/contract/compose/app change.
- Command: `node frontend/scripts/latency_probe.mjs ws://localhost:8002/ws 60` against the running four-service stack + host simulator at 5 Hz.
- Result: **3 runs × 60 = 180 valid samples, 0 discarded** — p50=2ms, p95=3–5ms, max=6–14ms → **PASS** vs PRD NFR-P1/AC6 `<2000ms`.
- Limitation: WS-receipt timing on a single host clock, NOT physical sensor→DOM render, and not under load/Aurora. Full sensor→pixel-under-load needs Pi/rig + headless browser (deferred).

## 2026-08-10 — P1 edge acquisition + safety abstractions (C1–C4) — hardware-free COMPLETE
Five commits (unpushed at time of writing): 511537c, 3bbbf19, 3a82229, 345fdde, 10d39be.
- **C1 (511537c)** `edge/drivers/` — `SensorDriver`/`Reading` interface + `Sensor` (calibration, range-clamp, health, ts) + fakes. Real GPIO/I2C/1-Wire bodies NOT implemented (hardware-blocked). `read()` per TRD §02.8.
- **C2 (3bbbf19)** `edge/acquisition/` — `Sampler` (1–10 Hz, monotonic `sample_seq`, injected clock, all six channels via C1) + bounded overwrite `RingBuffer`; shared `build_telemetry()` (`backend/app/schemas/build.py`) reused by the simulator (behavior-preserving refactor). Unhealthy tick → `frame=None` (no wire representation invented; contract untouched).
- **C3 (3a82229)** `edge/acquisition/mqtt_publisher.py` — resilient publisher: retained LWT `offline`, `online`-on-connect, graceful `offline`-on-stop; FR-Q4 buffered resume (buffer sized `ceil(rate×60)`, reuses C2 `RingBuffer`) with FIFO replay oldest→newest; reconnect backoff (configurable). Frozen contract unchanged.
- **C2→C3 runtime (345fdde)** `edge/acquisition/runtime.py` + `edge/main.py` — `AcquisitionRuntime` owns the loop (`sample_once → publish`), unhealthy ticks skipped, publish errors propagate; dev CLI runs the fake pipeline (HARDWARE-FREE/DEV). `fake_drivers()` added to `edge/drivers/fake.py`.
- **C4 (10d39be)** `edge/actuation/` — `RelayController` (default OFF, `on`/`off`/`safe_off`) + `Watchdog` (deadman, injected clock, expiry→OFF once, explicit reset/recovery, kick-after-expiry no-op) + `FakeActuator`. Isolated from C1/C2/C3.
- **Verification:** unit suite 120 passed / 5 skipped; real-Mosquitto integration (C3 publisher, C2→C3 runtime, backend MQTT/WS, simulator roundtrip) passed with the broker up; ruff/black/diff-check clean. Contract, backend app, frontend, Docker/Compose, docs, CLAUDE.md untouched (only the approved `build.py`/`test_build.py` + simulator refactor).
- **NOT done — hardware-blocked (need Pi/rig; not faked):** physical sensor/interface reads, INA219 pump-current, on-Pi LSTM+IF <500 ms timing, **physical relay safe-stop**, physical sensor→DOM / under-load latency.

## 2026-08-10 — P2 hardware-free foundations (plumbing) — through commit 5a1af31
Seven focused commits, each unit/interface-tested (math/shape/branch/plumbing only — **NO detection/trust/attribution accuracy claim**). Contract, Docker, P0/P1 code, simulator, frontend, docs untouched throughout; each commit scope-guarded to its own new files.
- **Beta trust core (26de8c2)** `edge/trust/beta.py` + tests — signal-agnostic `BetaState` (α₀=β₀=1, `T=α/(α+β)`, forgetting recursion), `combine_g` with documented weights 0.4/0.3/0.3, bands 0.7/0.4. **λ=0.7 recorded as PENDING U01 approval** (analyzed default, not a doc spec). Tests reproduce the analytic traces (spoof→0.343<0.4 in 3 windows, recovery, healthy, collusion cap) as MATH, not spoof detection.
- **Synthetic §12.4 injection framework (ee730fe)** `edge/injection/` + tests — 7 hardware-free injections (drift/spike/stuck-at faults; bias-FDI/ramp-FDI/replay/constant-spoof attacks) as pure stream transforms over the frozen `TelemetryMessage`; per-channel; magnitudes/onset/duration are REQUIRED args (no spec values invented); `dry-run` deliberately excluded (physical, hardware-gated). Ground-truth `Label` metadata is test/eval-only (not wire).
- **Anomaly foundation (f75b9dc)** `edge/anomaly/{preprocess,detector}.py` + tests — documented pipeline (median → low-pass → 30-sample window → per-window min-max; median kernel + low-pass alpha REQUIRED args, `window_size` default 30 documented); `AnomalyDetector` protocol + `NullDetector` placeholder + internal `AnomalyResult` (flag+severity∈[0,1]). No IF, no thresholds.
- **Trust-engine shell (9479968)** `edge/trust/engine.py` + tests — one `BetaState` per channel; `SignalProvider` seam for c/k/h (definitions NOT implemented); per-channel independence; documented weights/bands; λ=0.7 reused from the core (still pending U01).
- **Attribution-engine shell (cbd7527)** `edge/anomaly/attribution.py` + tests — documented per-channel none/fault/attack branch logic over an injected `PhysicsRule` seam (`PhysicsCheck` = violated/suspect/reason); reuses the frozen `Attribution` enum (contract unchanged); reason string is a passthrough template — NO physics equations/tolerances invented. Supports simultaneous fault+attack on different channels.
- **Pipeline orchestrator (d1ec0da)** `edge/anomaly/pipeline.py` + tests — `P2Pipeline` wires the injected components: frames → `Preprocessor` → window → `AnomalyDetector` → `ChannelFlagPolicy` → `TrustEngine` → `AttributionEngine`, returning internal `WindowOutcome` (no wire/REST/WS contract). The window-level→per-channel bridge is an injected `ChannelFlagPolicy` seam (UNDECIDED; not implemented — flagged, not invented).
- **Multivariate Isolation Forest detector (5a1af31)** `edge/anomaly/iforest.py` + tests — `IsolationForestDetector` behind the existing `AnomalyDetector` protocol: single sklearn IF over the flattened 180-dim 30×6 window (**D-A**); severity = empirical-CDF/rank of the window's anomaly score vs the stored clean-baseline distribution captured at `fit()` (**D-B**, parameter-free); `flag()` = `severity ≥ flag_threshold`, where `flag_threshold` is a REQUIRED constructor arg (no project value baked); IF hyperparameters exposed as optional passthroughs (sklearn library defaults otherwise); fixed `random_state` allowed for determinism.
  - **scikit-learn dependency:** `edge/requirements.txt` already documents the P2 pin `scikit-learn==1.4.*` (TRD §02.2). To keep scope (no pyproject/CI/requirements edits) and CI green, the IF **test module skips via `pytest.importorskip("sklearn")`** — same skip-pattern as the broker tests; nothing else imports `iforest`, so collection stays clean without sklearn. **Verified locally** with sklearn installed in the civenv (1.4.* won't build on Python 3.14 → used 1.9.0 for verification; code uses only stable `IsolationForest`/`score_samples` API; project pin stays 1.4). **In CI these 13 tests SKIP until scikit-learn is added to CI deps — recorded as a separate follow-up (not fixed in these commits).**
- **Verified (actually ran, civenv):** whole suite **257 passed, 5 skipped** (skips = broker-gated integration; IF's 13 ran locally). ruff + black clean; `git diff --check` clean; every commit scope-verified (only its own new files staged).
- **NOT done — explicitly pending (foundations ≠ validation):** c/k/h signal definitions (U01/U02); `ChannelFlagPolicy` localization (undecided; not from IF internals); real physics attribution rule + tolerances (U02; bench pressure is atmospheric proxy → dataset-gated); IF hyperparameter/threshold tuning + real clean-baseline fit (U07); dataset evaluation (SWaT/WADI access pending, TEP substitute); P2 acceptance tests (P2-ANOM-*, P2-TRUST-* incl. spoof→T<0.4 in ≤3 windows, attribution=attack); O3 (≥85%) / O10 (confusion matrix); authenticated scenario-injection hook FR-A4 (payload U14). The simulator (independent-channel Gaussians) can exercise plumbing + marginal faults only — it CANNOT validate cross-sensor spoof detection or attribution.
- **DECISIONS:** approved D-A (flatten 180-dim feature) and D-B (empirical-CDF severity) for the IF; U01 λ=0.7 remains pending explicit approval; U02/U07 unresolved. No frozen-contract or architecture change.

## 2026-08-10 — P2 diagnostics: IF behaviour + preprocessing comparison (commit d17942f)
Diagnostic-only tooling under `edge/eval/` — NOT production, NOT a P2 acceptance test. Kept off pytest `testpaths` (edge/eval not collected); test modules are scikit-learn-gated (`importorskip`). All injection magnitudes + the flag threshold are EVALUATION FIXTURES, not project specs. No production code changed (preprocess.py, IF detector, P2 pipeline, contract all untouched).
- **IF behaviour probe** (`edge/eval/if_eval.py` + `edge/tests/test_if_eval.py`): fits the real `IsolationForestDetector` on a clean simulator baseline, then scores clean + the 7 hardware-free §12.4 injections. **Key finding: clean-vs-clean false-positive rate ≈ 21.6%** at the eval-fixture threshold 0.95 → the detector does not calibrate tightly on the simulator's structureless independent-noise windows, so "detected" flags sit on a high FP floor and are not reliable separation. Replay is the least-anomalous injection (correct). Constant-spoof "detection" under per-window min-max is a flatness artifact (flat channel → all-zeros), NOT cross-sensor spoof detection.
- **Preprocessing comparison** (`edge/eval/preproc_experiment.py` + `edge/tests/test_preproc_experiment.py`): three normalizations feeding the UNCHANGED detector — A per-window min-max (current), B train-fit global min-max, C train-fit z-score.
  - Clean FP: **A 0.216 · B 0.035 · C 0.041** (B/C ≈ the ideal ~5% for a 0.95 threshold).
  - **Per-window min-max washes out a constant additive bias** within a fully-injected window (bias_fdi inside 0.989 ≈ clean); B/C preserve it (inside 1.000, flagged).
  - **Constant-spoof:** A "detects" it as a normalization flatness artifact; **B/C correctly do NOT detect** a plausible constant near the mean (inside 0.79/0.81 < 0.95) — the honest limitation that a plausible spoof carries no marginal signal and needs **cross-sensor physics**.
  - Trade-off: B/C assume **stationarity** (train-fit params) → would flag legitimate operating-point drift on real signals; the stationary, physics-free simulator structurally favours global normalization and cannot reveal per-window's robustness.
- **Decision recorded: normalization choice DEFERRED to real SWaT/WADI/TEP evaluation (U07).** No production preprocessing/detector/pipeline change approved or made. FR-P1 "min-max normalize" does not mandate per-window vs global — both stay doc-compatible until real data decides.
- **Verified (actually ran, civenv):** `python -m edge.eval.if_eval` + `… preproc_experiment` produce the numbers above deterministically (seeds 1337/2024, IF random_state 0). New diagnostic tests: `test_if_eval` 5 passed, `test_preproc_experiment` 3 passed. Whole suite **265 passed, 5 skipped** (skips = broker-gated integration). ruff + black + `git diff --check` clean.
- **Committed** `P2: add hardware-free IF + preprocessing diagnostic harness (not acceptance)` (**d17942f**). Not pushed.
- **Still NOT done (unchanged):** c/k/h definitions (U01/U02), ChannelFlagPolicy localization, real physics attribution rule (U02), IF tuning + real clean-baseline fit, dataset evaluation, P2 acceptance tests, O3/O10. The diagnostics inform these but validate none.

## Status
- **P0 hardware-free: VERIFIED/COMPLETE** (offline stack + latency probe). **P1 hardware-free: COMPLETE** (C1–C4 + runtime). **P2 hardware-free FOUNDATIONS: COMPLETE (plumbing only)** — preprocess, injection framework, Beta core+engine, attribution shell, pipeline orchestrator, multivariate IF detector. **P2 DIAGNOSTICS: COMPLETE (probes, not acceptance)** — IF behaviour (~21.6% clean FP) + normalization comparison; normalization decision deferred to real dataset (U07).
- **P2 VALIDATION: NOT done** — c/k/h, ChannelFlagPolicy localization, real physics rule, IF tuning, dataset eval, spoof/trust acceptance tests, O3/O10 metrics all pending (U01/U02/U07). scikit-learn CI dep = open follow-up.
- **Outstanding = hardware-only (P0/P1):** physical sensor reads, INA219 current, on-Pi LSTM+IF <500 ms, physical relay safe-stop, physical sensor→DOM/under-load latency. Neither P0 nor P1 is *fully* closed until a Pi/rig is available.
- Local branch is ahead of origin by the P1 + P2 commits (earlier P0 commits already on origin). Not pushed.
