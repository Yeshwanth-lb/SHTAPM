# CURRENT_STATE

> Implementation memory for SHTAPM. A fresh session reads this first, then
> `DECISIONS.md`, `TODO.md`, `IMPLEMENTATION_LOG.md`. Authoritative product spec
> lives in `../CLAUDE.md` and `../docs/` — not duplicated here.

**Last updated:** 2026-08-29 (P2 sections refreshed: corrected a stale
"D013 uncommitted" claim — D013 is in fact committed and pushed at `1c784e5`
— and recorded the new P2-ANOM-S1 `AdaptiveStealthFDI` addition, currently
uncommitted. See `DECISIONS.md` D013 and `P2_RESUME.md` §1a/§3a/§7a/§9 for
full detail; this file gives the short version. P0/P1 sections below are
unchanged and still accurate as of 2026-08-10.)

---

## Snapshot
- **Current phase:** P2 — Anomaly / Trust / Attribution (hardware-free FOUNDATIONS complete, incl. c/k/h + `ChannelFlagPolicy` + a minimal `PhysicsRule`; formal P2 acceptance suite now exists and has partially passed — see below). P0 + P1 hardware-free paths complete + verified.
- **Current milestone:** D013 (`DECISIONS.md`, committed and pushed at `1c784e5` — verified 2026-08-29) — `ChannelFlagPolicy` redesigned ("Candidate B": per-channel own-baseline two-sided test) and a minimal provisional `PhysicsRule` (`TrendSignPhysicsRule`, reusing D010's `k` heuristic) implemented to unblock `AttributionEngine`. Since then (2026-08-29), the one remaining hardware-free P2 acceptance gap was closed: a new `AdaptiveStealthFDI` injection type + its P2-ANOM-S1 scenario. The formal P2 acceptance suite (`edge/tests/test_p2_acceptance.py`) now attempts 11/14 Doc06 scenarios: **7/11 PASS** (full matrix: `P2_RESUME.md` §1a). **The 2026-08-29 P2-ANOM-S1 work is implemented, tested, lint/format clean, but UNCOMMITTED** — check `git status` before assuming it's on `origin/main`; D013 itself already is.
- **Overall completion:**
  - **P0 hardware-free: VERIFIED** — offline four-service stack (simulator→Mosquitto→backend→WebSocket→frontend) + E2E latency probe (p95 3–5 ms).
  - **P1 hardware-free: COMPLETE** — C1 driver abstraction, C2 sampler/ring buffer, C3 MQTT buffered-resume/LWT, C2→C3 runtime, C4 relay/watchdog. All unit + real-broker-integration verified.
  - **P2 hardware-free FOUNDATIONS: COMPLETE** — preprocess/windowing, injection framework (now 8 injections incl. `AdaptiveStealthFDI`), Beta trust core + engine, c/k/h signal providers, `ChannelFlagPolicy` (Candidate B, D013), a minimal provisional `PhysicsRule` (D013), attribution engine, pipeline orchestrator, multivariate IF detector.
  - **P2 SWaT DIAGNOSTICS: DIAGNOSTICALLY COMPLETE** (probes, not acceptance) — full campaign (normalization study, threshold sweep, root-cause screen, targeted diagnostics, IF hyperparameter grid) converged on **D012 signal coverage as the dominant demonstrated limitation** of the SWaT proxy validation. Normalization decision RESOLVED (per-window min-max confirmed, not changed). No further SWaT work planned unless explicitly requested — see `P2_RESUME.md` §3a.
  - **P2 FORMAL ACCEPTANCE: PARTIALLY done.** 7/11 attempted Doc06 scenarios PASS (D013 + the 2026-08-29 P2-ANOM-S1 addition); 4 FAIL with precisely diagnosed root causes; O3 structurally unreachable with the current minimal `PhysicsRule`. Full matrix + mandatory-blocker-vs-validation-limitation breakdown: `P2_RESUME.md` §1a/§7a.
  - **BLOCKED / PENDING (need Pi/rig — not faked):** physical sensor/interface reads, **INA219 pump-current**, **on-Pi LSTM+IF <500 ms** timing, **physical relay safe-stop**, and **physical sensor→DOM / under-load latency**. Neither P0 nor P1 is *fully* done until these are addressed. Real P2 accuracy validation (O2/O3/O4 on real sensors) is also gated here.

## Hardware-free E2E latency — VERIFIED (2026-08-10)
- Probe: `frontend/scripts/latency_probe.mjs` (no deps). Measures **simulator publish timestamp (`ts`) → WebSocket client receipt** — NOT physical sensor→DOM.
- **3 runs × 60 samples = 180 valid** (0 invalid/negative/discarded): p50 = **2 ms**, p95 = **3–5 ms**, max = **6–14 ms**.
- **PASS** vs PRD NFR-P1/AC6 `<2000 ms` (well under the <1s target).
- Unverified: physical sensor→DOM rendering and under-load (Aurora, real rig) latency — needs Pi/rig + headless browser.
- **Repository:** github.com/Yeshwanth-lb/SHTAPM (branch `main`; M1 d841404 … M3.5 8483283; CI-repair fab702b; offline-stack 75cef26; CA fixes c663ed6/6835b8e; port-remap/MQTT-retry/bind-fix committing now)

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
- **P0 Milestone 3.3** (committed 4c578c5) — backend MQTT telemetry ingestion: consumer + `TelemetryStore` + FastAPI lifespan + `/healthz`.
- **P0 Milestone 3.4** (committed 728838f) — backend WebSocket fan-out: `app/ws/{frames,broadcaster,routes}.py` + consumer `add_sink` seam; `/ws` Doc05 §05.8 frames.
- **P0 Milestone 3.5** (uncommitted) — minimal React consumer: `frontend/src/{App,main}.tsx`, `hooks/useTelemetryWebSocket.ts`, `features/telemetry/TelemetryView.tsx`, `lib/ws.ts` + RTL tests; `scripts/ws_smoke.mjs`. Reuses frozen TS contract, plain React state, capped-backoff reconnect. MQTT→backend live-verified under uvicorn; WS-serving-to-client + RTL/build gated to CI (sandbox blocks — see below).

## P2 — hardware-free foundations (2026-08-10) — plumbing COMPLETE, validation NOT
All unit/interface-tested (math/shape/branch/plumbing only — NO detection/trust/attribution accuracy claim):
- **Beta trust core** (26de8c2) `edge/trust/beta.py` — signal-agnostic `BetaState` (α₀=β₀=1, `T=α/(α+β)`), documented weights 0.4/0.3/0.3, bands 0.7/0.4, `combine_g`. **λ=0.7 = PENDING U01 approval** (analyzed default, not a spec number).
- **Synthetic §12.4 injection framework** (ee730fe) `edge/injection/` — 7 hardware-free injections (drift/spike/stuck-at + bias-FDI/ramp-FDI/replay/constant-spoof) as pure stream transforms; magnitudes/durations REQUIRED args (no spec values); `dry-run` excluded (physical). Ground-truth labels are test/eval-only, not wire.
- **Anomaly foundation** (f75b9dc) `edge/anomaly/{preprocess,detector}.py` — documented pipeline (median→low-pass→30-window→per-window min-max; kernel/alpha required args, window_size default 30); `AnomalyDetector` protocol + `NullDetector` + internal `AnomalyResult`.
- **Trust-engine shell** (9479968) `edge/trust/engine.py` — one `BetaState` per channel, `SignalProvider` seam for c/k/h (NO definitions), per-channel independence.
- **Attribution-engine shell** (cbd7527) `edge/anomaly/attribution.py` — documented none/fault/attack branch logic over an injected `PhysicsRule` seam; reuses frozen `Attribution` enum (contract unchanged); NO physics equations.
- **Pipeline orchestrator** (d1ec0da) `edge/anomaly/pipeline.py` — frames→preprocess→detector→`ChannelFlagPolicy`→trust→attribution; internal `WindowOutcome` (no wire contract). `ChannelFlagPolicy` (window-level→per-channel bridge) is an injected seam, NOT implemented.
- **Multivariate Isolation Forest detector** (5a1af31) `edge/anomaly/iforest.py` — single sklearn IF over flattened 180-dim 30×6 window (D-A); empirical-CDF/rank severity on stored clean-baseline scores (D-B); `flag_threshold` a REQUIRED config param (no baked value); IF hyperparameters optional passthroughs; fixed `random_state` allowed. **scikit-learn dep**: `edge/requirements.txt` pins `scikit-learn==1.4.*`; the IF test module **skips in CI until sklearn is added to CI deps** (separate follow-up) — verified locally (sklearn present).

### P2 NOT done — explicitly pending (superseded 2026-08-26 — see D013 update below; kept for historical trace)
- ~~c/k/h signal definitions... UNDECIDED~~ — **RESOLVED (provisional), D009/D010, implemented since before this session.**
- ~~`ChannelFlagPolicy` localization... UNDECIDED~~ — **RESOLVED (provisional, redesigned "Candidate B"), D013.**
- ~~Real physics attribution rule... UNDECIDED~~ — **PARTIALLY RESOLVED (minimal, provisional, narrow scope), D013** — see below for what remains.
- **IF tuning** — still UNTUNED; dataset-gated (U07). SWaT diagnostics (2026-08-25) now show hyperparameter changes have limited upside even where real signal exists — see `P2_RESUME.md` §3a.
- ~~Dataset evaluation... access pending~~ — **DONE.** SWaT.A1 access granted, harness built, full diagnostic campaign run and diagnostically complete (`P2_RESUME.md` §3a). SWaT/WADI structurally cannot satisfy O3 regardless (D011).
- **P2 acceptance tests:** now actually run (D013 + the 2026-08-29
  P2-ANOM-S1 addition, `edge/tests/test_p2_acceptance.py`) — 7/11 attempted
  PASS, 4 FAIL (root causes precisely diagnosed). Full matrix: `P2_RESUME.md`
  §1a.
- **O3 (≥85% attribution accuracy)** — still NOT produced, and **structurally
  unreachable** with the current minimal `PhysicsRule` (only names
  current/vibration, ~50–60% reliable even there) — a mandatory
  implementation blocker (broader rule), not a tuning gap. **O10** still NOT
  produced (blocked on hardware, not software).
- **Authenticated scenario-injection hook (FR-A4)** — not started (command payload U14).

### P2 — D013 (2026-08-25, committed `1c784e5`): ChannelFlagPolicy redesign + minimal PhysicsRule + first acceptance suite
See `DECISIONS.md` D013 and `P2_RESUME.md` §1a/§3a/§7a for full detail. Summary:
- `ChannelFlagPolicy` redesigned ("Candidate B": per-channel, own-baseline,
  two-sided empirical-CDF test) — fixes the P2-ANOM-H2 spike-misdirection bug;
  improves P2-TRUST-H2's flag rate 5x (13%→68%) without fully resolving it.
- Minimal, provisional `PhysicsRule` (`TrendSignPhysicsRule`, reuses D010's
  `k` heuristic verbatim) implemented — unblocks `AttributionEngine`'s wiring
  path (previously fully non-functional). Narrow scope, ~50–60% reliable.
- First-ever formal P2 acceptance suite written and run: **6/10 PASS**
  (P2-ANOM-H2, H3\*, E2\*, P2-TRUST-E1/E2/S1; \*=fixture-sensitive, ~50–60%
  reliable, not validated), **4 FAIL** (P2-ANOM-H1/E1, P2-TRUST-H1/H2 — all
  precisely root-caused, all documented validation limitations not missing
  code), **1 not attempted** (P2-ANOM-S1, no adaptive injection type).
- **D009 (`h`/GAMMA), D010's `k` formula, D011, D012, and IF/`c`'s own
  behavior are all explicitly UNCHANGED** by D013.
- **Full `pytest edge/` (2026-08-25): 327 passed, 4 failed, 2 skipped** — zero
  regressions outside the 4 documented, expected failures.
- **Committed and pushed** — `edge/anomaly/{policy,physics_rule}.py`,
  `edge/tests/{test_policy,test_physics_rule,test_p2_acceptance}.py`,
  `edge/eval/swat_eval.py` (plumbing only) are all on `origin/main` as of
  `1c784e5` (verified 2026-08-29 — corrects the "UNCOMMITTED" note that stood
  here through 2026-08-26).

### P2 — P2-ANOM-S1 (2026-08-29): AdaptiveStealthFDI injection + acceptance scenario
See `P2_RESUME.md` §1a/§7a/§9 for full detail. Summary:
- New 8th §12.4 injection, `AdaptiveStealthFDI` (`edge/injection/injections.py`):
  bias ramps then holds at a caller-chosen `residual_cap`, unlike unbounded
  `Drift`/`RampFDI` or instant `BiasFDI`/`ConstantSpoof`.
- Its P2-ANOM-S1 scenario (`edge/tests/test_p2_acceptance.py`) verifies the
  injection provably stays under a test-local "naive residual" bound
  throughout, then asserts the real, UNMODIFIED pipeline's trust for that
  channel still drops below `TRUSTED_MIN` — **PASS**, driven by the existing
  `ConsistencyProvider` (`c`) reacting to a sustained per-sample bias that a
  window-variance-based check (IF/`ChannelFlagPolicy`) does not; `channel_flags`
  never fires in this scenario. Verified at the committed fixture
  seed/parameters only — not multi-seed stress-tested.
- P2 acceptance now stands at **7/11 attempted PASS** (up from 6/10).
- **D009, D010, D011, D012, D013, and every existing IF/preprocessing/c/k/h/
  ChannelFlagPolicy/PhysicsRule behavior are explicitly UNCHANGED** — only a
  new injection type and its test were added.
- **Full `pytest edge/` (2026-08-29): 332 passed, 4 failed (same 4
  pre-existing, documented failures), 2 skipped** — zero regressions.
- **UNCOMMITTED as of this update** — `edge/injection/{injections,__init__}.py`,
  `edge/tests/{test_injection,test_p2_acceptance}.py`, plus this
  documentation refresh. ruff/black clean. Check `git status` before
  assuming this is on `origin/main`.

## P2 diagnostics (2026-08-10) — behaviour probes, NOT acceptance (commit d17942f)
Diagnostic-only tooling under `edge/eval/` (not on pytest `testpaths`, not in the production pipeline; scikit-learn-gated tests). All magnitudes + flag threshold are EVALUATION FIXTURES, not project specs. **No P2 acceptance criterion is claimed passed.**
- **IF behaviour probe** (`edge/eval/if_eval.py`) — real `IsolationForestDetector` on the simulator + the 7 §12.4 injections. Finding: **clean-vs-clean false-positive rate ≈ 21.6%** at the eval-fixture threshold 0.95 → per-window min-max on the simulator's structureless independent-noise windows does not calibrate tightly; "detected" flags sit on that FP floor and are not reliable separation.
- **Preprocessing comparison** (`edge/eval/preproc_experiment.py`) — per-window min-max (A, current) vs train-fit global min-max (B) vs train-fit z-score (C), all feeding the UNCHANGED detector:
  - clean FP: **A 0.216 · B 0.035 · C 0.041** (B/C ≈ ideal ~5% for a 0.95 threshold).
  - **per-window min-max washes out constant additive bias** within a fully-injected window (bias_fdi inside 0.989 ≈ clean, A) → B/C preserve it (inside 1.000, flagged).
  - **constant-spoof under A "detects" as a normalization flatness artifact** (flat channel → all-zeros), NOT cross-sensor spoof detection; B/C correctly do NOT detect a plausible constant near the mean (inside 0.79/0.81 < 0.95) — the honest limitation: a plausible constant spoof needs **cross-sensor physics**.
  - New risk of B/C: they assume **stationarity** (train-fit params) → would flag legitimate operating-point drift on real signals; the stationary, physics-free simulator structurally favours global normalization and cannot show per-window's robustness.
- **Decision:** **normalization choice DEFERRED to real SWaT/WADI/TEP evaluation (U07).** No production preprocessing/detector/pipeline change approved or made. FR-P1 "min-max normalize" does not mandate per-window vs global — both remain doc-compatible.
- **Reproduce:** `PYTHONPATH=backend:. python -m edge.eval.if_eval` · `… -m edge.eval.preproc_experiment`.

## In progress
- P2: foundations, SWaT diagnostics, D013's formal acceptance pass, and the
  2026-08-29 P2-ANOM-S1 addition are all complete. D013 is committed and
  pushed (`1c784e5`); the P2-ANOM-S1 work is implemented/tested/lint-clean
  but uncommitted, pending approval. Remaining work splits into one mandatory
  implementation blocker (a broader `PhysicsRule`, if O3 progress is wanted)
  plus real hardware, vs. documented validation limitations (IF/`c`/`h`
  tuning questions) — see `P2_RESUME.md` §7a.

## Next
- Commit the 2026-08-29 P2-ANOM-S1 work (pending approval). Then decide, per
  `P2_RESUME.md` §7a: whether to scope a broader `PhysicsRule` (the one
  remaining mandatory implementation blocker), or address the `c`/`h`/IF
  validation limitations (P2-TRUST-H1/H2, P2-ANOM-H1/E1) — both still need
  their own explicit scoping/approval before further code changes. λ=0.7
  (U01) remains PENDING, unrelated to D013.

## Environment gates (honest — sandbox limits, not code failures)
- **Docker image builds** (backend `pip`, frontend `npm`) fail cert-verify inside the build (gateway MITMs TLS; base images lack its CA). So the full four-service `up` can't be built here. Dockerfiles are standard/correct — no insecure workarounds added; they build on CI / a normal machine (frontend build already green in CI).
- Real uvicorn **WS serving to an external client** returns HTTP 403 in this sandbox (localhost `Upgrade` interception); app-level WS proven via Starlette TestClient (M3.4). Works under normal serving/CI.
- `npm install` blocked locally → no lockfile; RTL/`tsc`/`vite build` verified in CI.
- To verify the full stack + browser render, run on a machine without the TLS interception:
  `cp .env.example .env` → set `POSTGRES_PASSWORD` → `docker compose up --build` → open `http://localhost:5173`, `curl http://localhost:8002/healthz`, and run the host simulator (README). (Backend host port is 8002 → container 8000; browser WS = `ws://localhost:8002/ws`, baked via compose build.args.)
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
- P2: Beta math IMPLEMENTED (signal-agnostic core, 26de8c2) with λ=0.7 **pending U01 approval** (unchanged); `c`/`k`/`h` are RESOLVED (provisional, D009/D010) — `c`'s rank-based noise (P2-TRUST-H1) and `h`'s GAMMA=0.95 speed vs. a 3-window budget (P2-TRUST-H2) are now the specifically-identified open questions, not general "UNDECIDED".
- P2: fault-vs-attack physics/correlation attribution RULE — a minimal, provisional `PhysicsRule` now exists (D013, `TrendSignPhysicsRule`), unblocking `AttributionEngine`'s wiring. Still open: it only ever names current/vibration (no rule for the other 4 channels) and is only ~50–60% reliable even there — closing this for real (O3) needs a broader rule, a mandatory implementation blocker, plus real physics data that exists nowhere yet (bench-only, dataset-gated).
- P2: `ChannelFlagPolicy` (window-level IF → per-channel flags) RESOLVED (provisional, redesigned "Candidate B", D013) — per-channel own-baseline two-sided test, no longer cross-channel. Still U07-gated for real-data `tail_fraction` tuning.
- P2: IF hyperparameters + flag threshold UNTUNED — dataset-gated; SWaT diagnostics (2026-08-25) now show hyperparameter changes have limited upside even where real signal exists (`P2_RESUME.md` §3a).
- P2/P7: SWaT.A1 access GRANTED, harness built, full diagnostic campaign run and **diagnostically complete** — gates all P2 detection/attribution/trust real-data ACCEPTANCE and O3/O10 metrics regardless, since SWaT/WADI structurally cannot satisfy O3 or the literal six-channel semantics (D011). Real accuracy validation now needs bench hardware, not more dataset work.
- P2: P2-ANOM-S1 (adaptive/stealth injection type) — **RESOLVED (2026-08-29)**: `AdaptiveStealthFDI` implemented (`edge/injection/injections.py`) and its acceptance scenario PASSES; verified at the committed fixture seed/parameters only, not multi-seed stress-tested.
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
