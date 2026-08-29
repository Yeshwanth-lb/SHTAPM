# CURRENT_STATE

> Implementation memory for SHTAPM. A fresh session reads this first, then
> `DECISIONS.md`, `TODO.md`, `IMPLEMENTATION_LOG.md`. Authoritative product spec
> lives in `../CLAUDE.md` and `../docs/` — not duplicated here.

**Last updated:** 2026-08-30, end of session — **`d28de0b` is the clean
baseline** (`main`/`origin/main` identical, working tree clean). Today's
work: P2-ANOM-S1 (`b82f935`), the broader-`PhysicsRule` scoping decision
(`DECISIONS.md` D014, `5612a2a`), the P2-TRUST-H2 structural-limitation
decision (`DECISIONS.md` D015, `3a1be08`), and the P2-TRUST-H1/P2-ANOM-H1/E1
shared-root-cause documentation (`d28de0b`, no new decision created) —
**hardware-free P2 has no remaining mandatory software implementation** as
a result (see `P2_RESUME.md` §10 for the full handoff). A P3
implementation-readiness analysis was also performed (conversation-only,
nothing committed, **P3 work has NOT started**) — see `P2_RESUME.md` §10
and `TODO.md`'s P3 section. See `DECISIONS.md` D013/D014/D015 and
`P2_RESUME.md` §1a/§3a/§7a/§9/§10 for full detail; this file gives the
short version. P0/P1 sections below are unchanged and still accurate as of
2026-08-10.)

---

## Snapshot
- **Current phase:** P2 — Anomaly / Trust / Attribution (hardware-free FOUNDATIONS complete, incl. c/k/h + `ChannelFlagPolicy` + a minimal `PhysicsRule`; formal P2 acceptance suite now exists and has partially passed — see below). P0 + P1 hardware-free paths complete + verified.
- **Current milestone:** D013 (`DECISIONS.md`, committed at `1c784e5`) — `ChannelFlagPolicy` redesigned ("Candidate B": per-channel own-baseline two-sided test) and a minimal provisional `PhysicsRule` (`TrendSignPhysicsRule`, reusing D010's `k` heuristic) implemented to unblock `AttributionEngine`. Since then (2026-08-29), the one remaining hardware-free P2 acceptance gap was closed: a new `AdaptiveStealthFDI` injection type + its P2-ANOM-S1 scenario, **committed and pushed as `b82f935`** (verified 2026-08-30 — `main`/`origin/main` identical at `b82f935`). The formal P2 acceptance suite (`edge/tests/test_p2_acceptance.py`) now attempts 11/14 Doc06 scenarios: **7/11 PASS** (full matrix: `P2_RESUME.md` §1a). The broader-`PhysicsRule` scoping decision was closed and recorded as **D014** (2026-08-30, documentation-only — no new code): no new channel coverage added; `current`↔`temperature` deferred as the sole future candidate, gated on real bench data. Most recently, the P2-TRUST-H2 root cause was re-analyzed and recorded as **D015** (2026-08-30, documentation-only): the gap is a joint D009/D010 structural limitation, not primarily GAMMA — both decisions left unchanged, H2 remains FAIL.
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
- **Committed and pushed (2026-08-30)** — `docs: correct D013 project state
  documentation` (`ea437c6`) and `feat: add AdaptiveStealthFDI injection`
  (`b82f935`); `main` and `origin/main` are identical at `b82f935`.

### P2 — D014 (2026-08-30): broader-`PhysicsRule` scoping decision, no expansion
See `DECISIONS.md` D014 and `P2_RESUME.md` §5/§7/§7a for full detail. Summary:
- Scoping review of the four channels `TrendSignPhysicsRule` (D013) doesn't
  cover — `temperature`, `pressure`, `humidity`, `gas`. Conclusion: **no new
  channel coverage added**; `TrendSignPhysicsRule` is unchanged.
- `pressure` REJECTED — would reopen D010's already-recorded finding that
  BMP180 reads atmospheric pressure only, not water-line/discharge pressure.
- `humidity` REJECTED — the PRD's own "Design integrity note" (§12) and risk
  R6 explicitly require temperature/humidity to stay uncorrelated in the
  trust engine.
- `gas` REJECTED — no documented mechanical/electrical/thermal linkage to
  any other channel exists anywhere in the PRD/TRD.
- `current`↔`temperature` DEFERRED as the sole future candidate — physically
  plausible (I²R heating under load) and not PRD-forbidden, but no
  coefficient/lag/threshold is documented anywhere and no bench data has
  been collected. Gated on real bench hardware, not available here.
- **D009, D010, D011, D012, D013, and `AttributionEngine`'s single-
  `PhysicsRule` architecture are all explicitly UNCHANGED.** No code was
  modified by this decision — documentation-only.
- **O3 (≥85% attribution accuracy) remains structurally unreachable** — this
  decision does not change that and was never intended to.

### P2 — D015 (2026-08-30): P2-TRUST-H2 root cause established, D009/D010 unchanged
See `DECISIONS.md` D015 and `P2_RESUME.md` §1a/§6/§7/§7a for full detail. Summary:
- Read-only diagnostic replay (this pass, not committed) established that
  P2-TRUST-H2's gap is **not primarily `h`'s GAMMA speed**: the committed
  test uses `ConstantSpoof`, whose flat/zero trend leaves `k=1.0` the whole
  time (D010's non-paired-channel default, compounded by a documented
  flat-trend blind spot in the trend-sign rule) — this alone structurally
  floors `g` at 0.3, independent of `h`.
- Confirmed by replaying the scenario with `h` hypothetically collapsed to 0
  instantly (i.e. GAMMA/D009 entirely removed): trust still does not cross
  0.4 until window 5 after onset, not window 3. Only when `k` is *also*
  hypothetically forced to 0 does the trace reproduce D009's own
  approval-trail arithmetic (`T_3=λ³=0.343<0.4`) at exactly window 3 —
  meaning that arithmetic was implicitly valid only for an attack/channel
  combination where `g` can reach 0, which a flat spoof under D010's
  current `k` rule never allows, on any channel.
- **Decision (Option A): D009 and D010 both left unchanged.** P2-TRUST-H2
  is formally documented as a structural limitation, not fixed.
  P2-TRUST-S1's collusion resistance (the entire reason D009's GAMMA is
  slow) is fully preserved.
- **P2-TRUST-H2 remains FAIL. O4/AC2 is NOT claimed satisfied.** No code
  or test was changed — documentation-only.

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
- P2: foundations, SWaT diagnostics, D013's formal acceptance pass, the
  2026-08-29 P2-ANOM-S1 addition, the D014 broader-`PhysicsRule` scoping
  decision, and the D015 P2-TRUST-H2 scoping decision are all complete.
  D013 and P2-ANOM-S1 are committed and pushed (`main`/`origin/main` at
  `b82f935`); D014 and D015 are documentation-only decisions (no code).
  Remaining work is now down to one mandatory implementation blocker — real
  bench hardware — plus the two documented validation limitations still
  genuinely open: `c`'s rank-based noise (P2-TRUST-H1) and IF/normalization
  (P2-ANOM-H1/E1) — see `P2_RESUME.md` §7a.

## Next
**Not assumed to be coding — read `P2_RESUME.md` §10 first.** Hardware-free
P2 has no remaining mandatory software implementation (its 4 documented
FAILs are all hardware/data-blocked or decision-required limitations, not
missing code — none are fixable by more coding without either real bench
data or a new specification decision touching `c`, `k`'s non-paired
default, or GAMMA). The next session should explicitly ask the user
whether to: (a) formally enter **P3** (start by resolving U03/U04 — see
`TODO.md`'s P3 section and `P2_RESUME.md` §10; **P3 has NOT been started**,
only analyzed), (b) resolve one of the standing P2 decision-required items
(λ=0.7 sign-off/U01, `c`'s redefinition, FR-A4's payload/U14), or (c)
something else entirely. Do not default to P3 implementation, and do not
create a new decision (D016+) without the same propose-then-approve
sequence used for D014/D015. P2 work otherwise remains blocked on real
bench hardware (also the only path that could unblock D014's deferred
current↔temperature candidate).

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
- P2: Beta math IMPLEMENTED (signal-agnostic core, 26de8c2) with λ=0.7 **pending U01 approval** (unchanged); `c`/`k`/`h` are RESOLVED (provisional, D009/D010) — `c`'s rank-based noise (P2-TRUST-H1) remains an open question, **not an implementation bug**: analysis (2026-08-30, documentation-only, `P2_RESUME.md` §7a) found `c` shares its empirical-CDF-rank scoring architecture with `IsolationForestDetector.score()` (P2-ANOM-H1/E1) and is already at its Uniform(0,1) theoretical floor on clean data regardless of fit-corpus size — unlike ANOM-H1/E1 (which has a measurable, unimplemented, simulator-only fit-corpus-size improvement available), TRUST-H1 has no fix without redefining `c` itself. **P2-TRUST-H2's root cause RESOLVED (as a decision, not a fix) by D015 (2026-08-30)**: not primarily `h`'s GAMMA speed — `ConstantSpoof`'s flat trend leaves `k=1.0` (D010's non-paired-channel default) the whole time, structurally flooring `g` at 0.3 independent of `h`; diagnostic replay confirmed removing GAMMA entirely still misses the 3-window budget. `D009`/`D010` both left unchanged; P2-TRUST-S1's collusion resistance preserved; **H2 remains FAIL, O4/AC2 NOT satisfied**.
- P2: fault-vs-attack physics/correlation attribution RULE — a minimal, provisional `PhysicsRule` now exists (D013, `TrendSignPhysicsRule`), unblocking `AttributionEngine`'s wiring; still only ever names current/vibration, ~50–60% reliable even there. **Broadening scope RESOLVED (as a decision) by D014 (2026-08-30)**: `pressure`/`humidity`/`gas` REJECTED (D010 conflict / PRD design-integrity note / no documented basis); `current`↔`temperature` DEFERRED as the sole future candidate, gated on real bench data that doesn't exist yet. O3 remains structurally unreachable regardless.
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
