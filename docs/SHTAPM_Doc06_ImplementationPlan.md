# Document 06 — Implementation Plan (Step-by-Step Build Sequence) *(enhanced)*
### SHTAPM — strict phased roadmap with exhaustive test cases
**Companion to:** PRD v1.0 · TRD (02) · App Flow (03) · UI/UX "Aurora" (04) · Backend Schema (05)
**Status:** Build-ready · **Version:** 1.1 (adds Aurora build steps + glass/motion/perf tests in Phases 5–6)

> Strict order. Each phase: **Goals & Build Sequence → Test Cases (Happy/Edge/Sad) → Done Criteria.** Do not start a phase until the prior phase's Done Criteria are green. E2E hardware→pixel tests appear from Phase 7. **v1.1** folds the Aurora design language (Doc 04) into the frontend phases with explicit performance/accessibility gates so beauty never costs the live-stream budget.

---

## Phase 1 — Project Setup, Repo, Env Vars
**Goals & build sequence**
1. Monorepo per TRD §02.6; git + Conventional Commits + pre-commit (ruff/black/eslint/prettier).
2. `docker-compose.yml` for four services (mosquitto, postgres+timescale, backend, frontend) — wired, empty.
3. `.env.example` with every TRD §02.7 variable (incl. `VITE_AURORA_MOTION`, `VITE_REDUCE_TRANSPARENCY_DEFAULT`); loaders per service.
4. Self-host fonts (Geist/Geist Mono) locally — **no external CDN** (offline-demo rule).
5. CI skeleton (lint + test placeholders).

**Test cases**

| Type | Case | Expected |
|------|------|----------|
| Happy | `docker-compose up` (offline) | four containers start; health endpoints reachable; no internet needed |
| Happy | Env loads per service | missing var → clear boot error naming it |
| Happy | Fonts load offline | Geist renders with no network |
| Edge | Wrong-type env (`SAMPLE_RATE_HZ="x"`) | validation error at boot, not runtime |
| Edge | Port already in use | clear report + documented override |
| Sad | Missing `.env` | refuse to boot, actionable message, no half-start |
| Sad | Corrupt compose | fail fast in CI |

**Done criteria:** clean offline `up` on a fresh machine; all envs validated; fonts self-hosted; lint/format enforced; README bring-up verified by a second person.

---

## Phase 2 — Database Schema & Auth
**Goals & build sequence**
1. SQLAlchemy models for every Doc 05 table; Alembic initial migration; enable TimescaleDB + hypertables (`sensor_readings`,`decisions`).
2. Continuous aggregates (`readings_1min`,`decisions_5min`) + retention policies; device `health_state` rollup trigger/logic.
3. Auth: register/login/refresh/logout; bcrypt; JWT; RBAC dependency; RLS + per-request `app.user_id/app.role`.
4. Seed: admin, analyst, operator, one device, thresholds, six `sensors` rows (with `display_hue`).

**Test cases**

| Type | Case | Expected |
|------|------|----------|
| Happy | Migrate up/down | applies + rolls back cleanly |
| Happy | Login valid | access+refresh; role in token |
| Happy | Hypertable insert + rollup | reading stored; `devices.health_state` updates |
| Edge | Refresh at expiry boundary | rotates once; old revoked |
| Edge | Operator queries another owner's device | RLS → empty (not error) |
| Edge | 10k readings bulk insert | within budget; index used (EXPLAIN) |
| Sad | Login wrong password | 401, generic, no user enumeration |
| Sad | Reused rotated refresh | 401 + token family revoked |
| Sad | Non-admin writes thresholds | 403 + audit_log entry |
| Sad | SQLi attempt in params | parameterized; no leak |

**Done criteria:** all auth flows pass; RBAC+RLS verified for three roles; aggregates + health rollup working; migrations reversible; seed yields a working login.

---

## Phase 3 — Hardware / Firmware Prototyping & Connectivity
**Goals & build sequence**
1. Pi OS + interfaces; one driver per sensor (`read() → {value,unit,ts,healthy}`); calibration + range clamp.
2. Sampler at 1 Hz → telemetry frame (shared contract) → local ring buffer.
3. `paho-mqtt` publisher → `…/telemetry`; retained LWT status; reconnect/backoff; buffered resume.
4. Relay + watchdog: manual stop/start; watchdog defaults pump OFF on process death.

**Test cases**

| Type | Case | Expected |
|------|------|----------|
| Happy | 10-min six-channel run | <1% dropped; frames valid vs contract |
| Happy | INA219 idle vs pump-load | current delta clearly above noise |
| Happy | Manual relay stop/start | pump toggles; state published |
| Edge | 10 Hz burst | stable, no overflow |
| Edge | Broker down 30s then up | buffered, replayed in order, no loss |
| Edge | Sensor at range boundary | clamped/flagged, not garbage |
| Sad | Unplug DS18B20 mid-run | channel `healthy=false`; others continue |
| Sad | Loose I²C (SDA) | handled error + reconnect |
| Sad | Kill edge process | watchdog → pump OFF (safe) |

**Done criteria:** six channels stream reliably; LWT online/offline works; relay + watchdog safe-state verified physically; buffered resume proven.

---

## Phase 4 — Backend API & WebSocket/MQTT Broker
**Goals & build sequence**
1. Mosquitto config (auth, topics, persistence); subscriber tasks (telemetry/decision/ledger/status) with Pydantic validation → DB writes + `health_state` rollup.
2. WebSocket gateway + connection manager (per-device scoping, token auth on connect); **immediate** fan-out (off DB hot path); emit `system_health` frames (Aurora feed).
3. REST endpoints (Doc 05.7): devices, readings/decisions history, alerts, ledger + verify, thresholds, inject→MQTT, system health.
4. Ledger verify service (walk chain, detect break, report `broken_at`).

**Test cases**

| Type | Case | Expected |
|------|------|----------|
| Happy | Telemetry MQTT→DB→WS | client sees live frames in order <1s |
| Happy | Inject via REST | command published; audit + ledger written |
| Happy | Ledger verify intact | `{valid:true}` |
| Happy | system_health frame | carries `health` + `e2e_latency_ms` |
| Edge | 5 concurrent WS clients | all receive; no lag beyond budget |
| Edge | WS reconnect | resumes; no dup storm |
| Edge | Empty history range | 200 + empty set |
| Sad | Malformed MQTT payload | rejected + logged; subscriber stays up |
| Sad | Tampered ledger block | `{valid:false, broken_at:n}` |
| Sad | Unauthed WS connect | rejected at handshake |
| Sad | Operator hits admin REST | 403 + audit |

**Done criteria:** live MQTT→WS <1s; all REST role checks pass; ledger verify catches tamper; `system_health` feed emits; malformed input never downs a service.

---

## Phase 5 — Frontend Admin Dashboard & Core Features (Aurora foundation)
**Goals & build sequence**
1. Vite+TS app; Tailwind + **Aurora tokens** (Doc 04 §04.2); shadcn/ui primitives restyled to glass; Framer Motion presets in `lib/motion`.
2. `components/aurora/`: **MeshBackground** (health-reactive blurred orbs), **GlassTile** (bento cell), **TactileToggle** (claymorphic control).
3. Auth screens (glass login over calm aurora) + token handling + silent refresh; protected glass layout (sidebar rail, floating top bar, connection + latency chips).
4. `useWebSocket` reconnecting hook + Zustand live store; `useHealthField` hook mapping `system_health.health` → Aurora mood; TanStack Query REST clients.
5. Pages wired to real data: Overview (bento), Device Detail (curated cockpit), Alerts, Ledger, Devices, Settings, Users, System — with all empty/error/demo states (Doc 03.6).

**Test cases**

| Type | Case | Expected |
|------|------|----------|
| Happy | Login → Overview | aurora blooms; glass bento tiles render |
| Happy | Open Device Detail | WS subscribes; live values populate cockpit |
| Happy | Health→Aurora mapping | healthy=teal/violet; warning=amber; critical=rose |
| Happy | Ack an alert | optimistic update + server confirm |
| Edge | Tablet 768px | bento re-tiles (FLIP); nothing clipped |
| Edge | 60-min session | no memory leak; ring buffer stable |
| Edge | Burst of 50 events | virtualized lists stay responsive |
| Edge | `VITE_REDUCE_TRANSPARENCY=on` | glass → opaque; full data parity |
| Sad | WS drops | "Reconnecting…" glass state; auto-resume; no blank |
| Sad | Backend 500 on history | error card + retry; live panel unaffected |
| Sad | Operator opens `/users` | fade-redirect + toast |
| Sad | Expired session | toast + fade to login; return route kept |

**Done criteria:** every route renders real data + all empty/error/demo states; auth+RBAC enforced client-side; Aurora background reacts to health; responsive desktop+tablet; reduce-transparency parity; no console errors.

---

## Phase 6 — UI Polish & Live Data Visualization (Aurora completion)
**Goals & build sequence**
1. **uPlot live charts** in glass: 60s scroll, luminous line + soft glow, breathing cursor orb, 140ms ease-in; per-channel `display_hue`; **fault=amber tile glow, attack=rose glow + line shimmer, VIRTUAL=dashed violet + purple aura + pulsing chip**.
2. **Trust constellation** (ECharts): six luminous orbs sized/glowing by score, shrink+cool on drop (500ms), rekindle on recovery; dense bar-equalizer fallback.
3. **RUL/health gauge** (ECharts radial, eased tip, single bloom on state change); **health hero** thin numeral.
4. **RL Action Log** + **Ledger stream** in `--glass-inset` wells: bloom-in entries, mono truncated hashes, verify teal cascade, tamper rose fracture.
5. **System-health micro-tiles** incl. live E2E latency chip (teal/amber/rose); global **motion grammar** + `prefers-reduced-motion` gating; full a11y pass.

**Test cases**

| Type | Case | Expected |
|------|------|----------|
| Happy | 1 Hz stream | luminous lines scroll at 60fps; no jank |
| Happy | Trust drop | orb shrinks + cools; alert blooms |
| Happy | VIRTUAL channel | dashed violet + purple aura + "VIRTUAL" chip |
| Happy | Ledger verify | valid blocks pulse teal in cascade |
| Edge | Rapid attack→heal→fault | overlays/aurora render in correct order, no race |
| Edge | `prefers-reduced-motion` | aurora freezes, blooms disabled, data still updates |
| Edge | Colorblind sim (red/green) | status distinguishable via shape+size+label |
| Edge | ≤4 orbs + ≤6 blur layers | stays within GPU budget; fps ≥55 |
| Sad | Bad/NaN data point | chart skips gracefully, no crash |
| Sad | Latency >2s | chip turns rose (honest, not hidden); aurora effects shed first |
| Sad | fps < 50 | auto-downgrade (glow off / blur reduced), live data unaffected |

**Done criteria:** visuals match Doc 04; fault vs attack vs VIRTUAL is visually unmistakable *and* label-backed; AA accessibility verified (contrast floor over brightest aurora, motion-safe, reduce-transparency); 60-min soak holds 60fps; performance auto-downgrade proven.

---

## Phase 7 — End-to-End Integration Testing (hardware → pixel)
**Goals & build sequence**
1. Full stack on the real rig via compose; run PRD §18.4 script end to end.
2. Latency-probe harness: timestamp a synthetic physical event → assert DOM update <2s (with Aurora effects live).
3. Recorded-session **fallback/replay mode** behind a toggle (identical Aurora UI path).
4. Chaos passes: Wi-Fi drop, broker kill, sensor unplug, backend restart — mid-stream.

**Test cases (E2E)**

| Type | Case | Expected |
|------|------|----------|
| Happy | Physical vibration change | luminous line reflects <2s; health + aurora update |
| Happy | UI-inject pressure spoof | trust orb cools → isolate → dashed violet VIRTUAL → prediction continuous, all on screen |
| Happy | Empty reservoir | pump physically safe-stops; UI shows safe_stop + ledger block; aurora rose heartbeat |
| Happy | Tamper ledger live | verify cascade fractures rose on screen |
| Edge | Venue Wi-Fi drop | edge buffers; UI "reconnecting"; recovers, no loss |
| Edge | Full-load latency (aurora + all panels) | still <2s |
| Edge | Rapid attack→heal→fault | correct ordered rendering + aurora crossfades |
| Sad | Pump dead on demo day | fallback/replay runs identical narrative + aurora |
| Sad | Sensor unplugged mid-demo | channel flagged; self-heal to VIRTUAL; demo continues |
| Sad | Broker killed mid-demo | degraded glass state; auto-recover; no crash |

**Done criteria:** full §18.4 sequence runs twice (live + fallback); measured sensor→UI <2s under load *with Aurora live*; every chaos case recovers gracefully; all PRD acceptance criteria (AC1–AC10) green.

---

## Phase 8 — Deployment & Demo Prep
**Goals & build sequence**
1. Production compose profile; frontend built + nginx-served; backend uvicorn/gunicorn; TLS where networked.
2. Single-machine **offline demo profile** (broker+db+backend+frontend local, fonts self-hosted) — venue-proof.
3. Seed a compelling replay dataset; automate PRD §18.3 pre-flight self-check; tune `VITE_AURORA_MOTION` for the demo laptop's GPU.
4. Backup/export: session telemetry + ledger export for the report; teardown script.

**Test cases**

| Type | Case | Expected |
|------|------|----------|
| Happy | Offline profile bring-up | full demo works with no internet, aurora included |
| Happy | Pre-flight self-check | all-green or names the failing item |
| Edge | Cold boot on demo laptop | services start in order (db→broker→backend→frontend); aurora ≥55fps |
| Edge | Projector/second screen | UI legible at room distance; glass contrast holds |
| Edge | Weak-GPU laptop | `VITE_AURORA_MOTION=reduced` keeps 60fps data path |
| Sad | One service fails | self-check blocks demo start + says which |
| Sad | SD/DB corruption on Pi | documented recovery; fallback to replay |

**Done criteria:** one-command offline bring-up verified on the actual demo laptop (aurora tuned to its GPU); pre-flight passes; export produces report artifacts; rehearsed twice including fallback.

---

## Cross-cutting definition of done (whole build)
- All eight phases' Done Criteria green.
- Every **Must** feature (PRD Appendix C) passes Happy + Edge + Sad.
- Sensor→UI latency **<2s** under load *with Aurora live*; self-heal **<500ms** (edge, UI-independent); safe-stop verified physically.
- Ledger tamper-detection verified live; RBAC + RLS enforced; auth flows complete.
- Aurora accessibility verified: contrast floor over brightest orb phase, color+shape/label everywhere, `prefers-reduced-motion` + reduce-transparency parity.
- Performance auto-downgrade proven: effects shed before the data path ever degrades.
- Demo runs twice end-to-end (live + fallback) with zero manual DB pokes.
- Shared data contract identical across firmware, DB, API, WS, and TS types.

---

### Implementation intent, in one line
Eight strict phases, each gated by Happy/Edge/Sad tests, that build SHTAPM from an offline repo to a rehearsed live demo — layering the Aurora interface on top of a proven data path with explicit performance and accessibility gates so the dashboard is breathtaking *and* never drops a frame of the 1 Hz truth beneath it.
