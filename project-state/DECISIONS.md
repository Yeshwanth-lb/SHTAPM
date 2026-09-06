# DECISIONS

> Architectural / implementation decisions of record. Newest changes append; a
> decision that supersedes another references it and states why (state rule 7).
> Anything not decided by `../docs/` or the approved roadmap is marked UNDECIDED.

| Field | Meaning |
|-------|---------|
| ID | stable identifier (D0xx) |
| Date | decision date |
| Decision | what was decided |
| Reason | why |
| Affects | components / phases impacted |

---

### D001 — PRD is authoritative for the phase roadmap
- **Date:** 2026-08-09
- **Decision:** The PRD (`docs/SHTAPM_PRD-4.md`, §20) defines the authoritative phase order P0–P7. Its numbering governs when PRD and Doc06 disagree.
- **Reason:** PRD declares itself the single source of truth and explicitly defines the product build order.
- **Affects:** All phases; planning; `TODO.md` structure.

### D002 — Doc06 is the detailed implementation/test spec mapped into PRD phases
- **Date:** 2026-08-09
- **Decision:** `docs/SHTAPM_Doc06_ImplementationPlan.md` is retained as the detailed build/test specification. Its tasks and Happy/Edge/Sad test cases are reconciled into the PRD phase structure; Doc06's own phase numbering is NOT followed blindly. Mapping: Doc06 setup→P0; hardware/acquisition→P1; DB/backend/auth→P4 (schema+contract are early cross-cutting prerequisites); frontend→P5; UI polish→P5/P6; E2E→P6; deploy/demo→P6.
- **Reason:** Doc06 holds the concrete, testable task detail the PRD lacks; discarding it loses the test gates. Doc06 has no phases for PRD P2/P3 edge intelligence or P7 evaluation — those come from the PRD and must not be omitted.
- **Affects:** All phases; `TODO.md`; test gates.

### D003 — Edge safety loop must never depend on backend/cloud/network
- **Date:** 2026-08-09
- **Decision:** The `sense→detect→attribute→decide→heal→actuate` loop runs entirely on the Raspberry Pi edge node. Backend/cloud is never in the safety-critical path. The dry-run→safe-stop path is fully edge-resident.
- **Reason:** Satisfies the <500ms self-heal budget and the "no network dependency for a safety stop" requirement; a core defensible design point.
- **Affects:** Edge (P1–P3), backend (P4), architecture globally. TRD §02.1, PRD §10.2/Appendix F.

### D004 — Ledger is a SHA-256 hash chain; Hyperledger is future scope
- **Date:** 2026-08-09
- **Decision:** The tamper-evident ledger is implemented as a SHA-256 hash chain (`this_hash = sha256(index+ts+payload_hash+prev_hash)`) with a verifier. A real permissioned blockchain (Hyperledger) is explicitly out of scope for this implementation.
- **Reason:** Hash chain meets the tamper-detection requirement at zero infra cost; PRD marks full Hyperledger "Won't (now)" and recommends the hash chain unless multi-party trust is required.
- **Affects:** Ledger (P3 edge writer, P4 verifier/store), DB `ledger_blocks` (Doc05).

### D005 — A hardware-free telemetry simulator/replay source will be used
- **Date:** 2026-08-09
- **Decision:** A simulator/replay source emitting the frozen data contract over MQTT will stand in for the physical rig, so backend and frontend can be developed, tested, and demoed without the Raspberry Pi/bench rig. It also serves as the live-demo fallback (PRD R1/R2).
- **Reason:** No Pi/rig is attached to the current dev environment; most of the codebase (P4/P5, plus P2/P3 on recorded data) is hardware-independent. Also de-risks the demo.
- **Affects:** P0 (build the simulator), P2–P6; the frozen contract (D006).

### D006 — Frozen shared telemetry/decision/ledger contracts stay consistent everywhere
- **Date:** 2026-08-09
- **Decision:** One frozen shared data contract (telemetry, decision, ledger message shapes; field names per PRD §10.3 and Doc05 §05.8) is used verbatim across firmware, simulator, backend, database, WebSocket frames, and frontend TypeScript types. No component invents or renames fields.
- **Reason:** "The contract is sacred" (TRD §02.6) — coherence across tiers; changing a name in one place silently breaks the others.
- **Affects:** All tiers, all phases.

### D007 — Doc05 §05.8 is authoritative for the canonical wire contract
- **Date:** 2026-08-09
- **Decision:** The frozen shared contract (D006) uses **Doc05 §05.8** field names and shapes. PRD §10.3 shorthand is superseded. Explicit rulings:
  - **A/B** — telemetry `sensors` and decision `trust` use the full channel names `temperature, vibration, pressure, humidity, gas, current` (never `temp`/`vib`/`s1..s6`).
  - **C** — decision self-healing is flat `isolated[]` / `substituted[]` (never nested `healing:{}`).
  - **D** — the canonical ledger message keeps `payload_hash` (required for hash-chain verification, FR-L2). Its omission from the Doc05 §05.8 WS example is a doc omission, not permission to drop it. Canonical ledger fields: `device_id, ts, block_index, event, payload_hash, prev_hash, this_hash`.
  - **E** — `type` is a WebSocket envelope concern only. MQTT topics (`telemetry/decision/ledger/status/command`) identify the category, so MQTT payloads carry no `type`; WS frames are `{"type": <cat>, **payload}`. Payload fields are otherwise identical on MQTT and WS.
- **Reason:** CLAUDE.md source-of-truth hierarchy puts schema under Doc05; its names are used consistently across DB columns, ENUMs, and WS frames. Resolves the PRD §10.3 ↔ Doc05 §05.8 conflicts flagged before M2.
- **Affects:** shared contract everywhere (D006); `backend/app/schemas/contracts.py`, `frontend/src/types/contracts.ts`; future simulator/edge/backend/WS/frontend (P1–P5).
- **Supersedes:** nothing (refines D006). Message field `event`/`health` map to DB columns `event_type`/`health_state` (message-vs-storage layer; not a conflict).

### D008 — Hardware-free simulator lives in top-level `simulator/`, isolated from `edge/`
- **Date:** 2026-08-09
- **Decision:** The D005 telemetry simulator is a top-level `simulator/` package, deliberately separate from `edge/` (the Raspberry Pi drivers, P1). It reuses the canonical contract from `backend/app/schemas` (D006/D007) rather than duplicating field names; for now it imports it via `PYTHONPATH` (`backend` on path). Root pytest config sets `pythonpath = ["backend", "."]` + `--import-mode=importlib` so the whole suite runs from one command.
- **Reason:** Keeps the dev/replay source cleanly isolated from real hardware code (instruction + PRD framing) while honoring the single-contract rule. A dedicated shared contract package may be introduced later when edge (P1) also needs the contract — noted, not resolved.
- **Affects:** `simulator/` (M3), test wiring (`pyproject.toml`), future edge P1 contract import.

### D009 — `h` (historical-reliability) signal formulation for TrustEngine
- **Date:** 2026-08-23
- **Decision:** `h` is implemented as a per-channel slow exponential moving average of binary
  healthy/unhealthy window outcomes: `h_ch,t = GAMMA * h_ch,t-1 + (1 - GAMMA) * outcome_ch,t`.
  Approved parameters: **GAMMA = 0.95** (approved slow forgetting factor; half-life ~13 windows,
  chosen to be significantly slower than lambda=0.7's ~2-window half-life); **H_INIT = 1.0**
  (clean-history prior). `outcome_ch,t in {0.0, 1.0}` supplied by the caller as a bool via
  `record_outcome(channel, was_healthy)`. Implemented as `HReliabilityProvider` in
  `edge/trust/h_reliability.py`, satisfying the existing `SignalProvider` protocol.
  `h` is independent of `c` (different observation type, timescale, object), independent of
  `g` and `BetaState` (no shared computation), and agnostic about the source of `was_healthy`
  (`ChannelFlagPolicy` remains a seam). Causal ordering: `h_t` reflects outcomes through
  window `t-1`; the caller invokes `record_outcome` before `TrustEngine.update_from_providers`.
- **Reason:** Satisfies FR-T2 (weight historical reliability), P2-TRUST-S1 (collusive attack
  cannot hold full trust — `h` degrades at 0.95^n, slower than `k` can compensate), and
  FR-T4 (recovery is possible via the same EMA formula).
- **Affects:** `edge/trust/h_reliability.py` (new), `edge/trust/__init__.py`; future
  `edge/anomaly/pipeline.py` (caller of `record_outcome`).
- **Partially resolves U01:** `h` definition and memory length decided. **Remaining U01 open:**
  lambda=0.7 (PENDING explicit approval); `c` signal definition (UNDECIDED).
- **Does NOT resolve:** U02 (`k`/physics), `ChannelFlagPolicy`, IF tuning, normalization (U07).

### D010 — `k` (cross-sensor correlation) signal: provisional current↔vibration heuristic
- **Date:** 2026-08-24
- **Decision:** `k` is implemented against the **current↔vibration** channel pair, not
  current↔pressure (the pair literally named in the PRD/demo script). Rule: compare each
  channel's early-half vs. late-half window mean (split at `window.size // 2`, not a
  hardcoded index) to get a trend sign in `{-1, 0, +1}`; `k_current = k_vibration = 1.0`
  if the two trend signs multiply to `>= 0` (same direction, or either/both flat), else
  `0.0`. Non-involved channels (temperature, pressure, humidity, gas) always get `k=1.0`
  (no rule defined for them — this is not a health claim, `c`/`h` cover those channels).
  On disagreement both current and vibration receive `k=0.0` (indeterminate which channel
  lies; `AttributionEngine` refines later). No tunable threshold/epsilon. Implemented as
  `CorrelationProvider` in `edge/trust/k_correlation.py`, satisfying `SignalProvider`.
- **Reason:**
  - **Why not current↔pressure:** the bench `BMP180` reads **atmospheric** pressure, not
    water-line/discharge pressure — the PRD's implied physics (pump running → discharge
    pressure rises with current) cannot be realized on the current bench hardware (TRD
    proxy constraint C6). Confirmed unavailable on SWaT/WADI too (neither dataset exposes
    a continuous motor-current channel; see U07 report §5).
  - **Why current↔vibration:** both `INA219` (current) and `ADXL335` (vibration) are
    direct measurements of actual pump mechanical state (load → bearing stress), so the
    pair is realizable on the bench today without new hardware.
  - **Why a parameter-free heuristic, not a learned/expert-constant model:** the simulator
    generates all channels as independent Gaussians (no real correlation to fit or
    validate against), and defining a numeric physics tolerance without real data would
    be inventing a spec — explicitly disallowed. A sign-only trend comparison needs no
    tunable constant, so it can ship now and be replaced once real data exists.
  - **Why both channels penalized on disagreement:** the rule only detects that the pair
    is inconsistent, not which member is lying; assigning blame requires attribution
    logic that doesn't yet exist. This avoids inventing an attribution rule prematurely.
- **Affects:** `edge/trust/k_correlation.py` (new), `edge/anomaly/pipeline.py` (wires
  `record_window`), `edge/trust/engine.py` (consumes via `SignalProvider`).
- **Partially resolves U02:** channel pair and heuristic approach are now decided and
  implemented. **Still open:** whether current↔vibration trending is a real physical
  relationship at bench scale, what tolerance (if any) is needed beyond pure sign
  comparison, and whether the "one rising + one flat passes" limitation needs fixing —
  all require real pump data (bench or a labeled dataset) and are explicitly deferred to
  U07/domain review, not resolved here.
- **Does NOT resolve:** `ChannelFlagPolicy` real-data validation, IF tuning, normalization
  (U07), O3 bench-scenario attribution accuracy.

### D011 — SWaT-based P2 validation methodology: frozen scope (dataset access NOT yet approved)
- **Date:** 2026-08-24
- **Decision:** The following methodology is approved for a future SWaT-based P2
  validation pass, **once dataset access is separately authorized**:
  - **Channel mapping (B):** reuse the existing frozen contract unmodified.
    Relabel six SWaT tags onto our six channel field names
    (temperature/vibration/pressure/humidity/gas/current) purely as a
    plumbing/proxy substitution — explicitly NOT a claim that any SWaT tag is
    physically equivalent to the bench channel it's relabeled onto. The
    specific six tags are NOT chosen yet and will not be chosen until SWaT's
    own tag dictionary (`readme.docx`, bundled with the dataset — see U07
    report §2) is in hand.
  - **`k` (correlation signal) (C):** may run mechanically if the pipeline
    requires it, but is **excluded from validation evidence** — no `k` metric
    is to be reported, no claim of `k` validation is to be made, and any
    report must label `k` as physically unvalidated/meaningless on SWaT
    (current/vibration are confirmed absent from both SWaT and WADI, D010,
    U07 report §5). `k`'s formula is NOT to be redesigned or adapted for SWaT.
  - **`AttributionEngine` / O3 (D):** deferred entirely for this phase. No
    `PhysicsRule` is to be designed or implemented now. `AttributionEngine`
    is BLOCKED (no concrete `PhysicsRule` implementation exists anywhere in
    the codebase — verified by direct inspection 2026-08-24). No O3 claim may
    be drawn from SWaT results.
  - **WADI 6-of-15 tag-localization check (E):** REJECTED from the main
    validation plan — sample size (n≈6) judged too small to provide
    meaningful validation value. May be revisited separately later, not as
    part of this methodology.
  - **Temporal train/eval separation (F):** hard requirement. Any fitting of
    IF, `c`, normalization parameters, thresholds, or other
    learned/statistical parameters must use only data preceding the
    evaluation period; no leakage from attack/evaluation windows into
    fitting. Must be documented explicitly in the eventual evaluation
    harness (e.g. `edge/eval/swat_eval.py`, not yet created).
- **Reason:** Freezes the validation *shape* independent of whether/when
  dataset access is granted, so that decision (a separate approval, see
  below) doesn't also require re-deriving methodology under time pressure.
  Each sub-decision follows directly from the U07 feasibility findings
  (`U07_DATASET_FEASIBILITY_REPORT.md`) and D010's confirmed absence of
  current/vibration in both datasets.
- **Affects:** a future `edge/eval/swat_eval.py` (not yet created), the
  eventual SWaT-tag-mapping decision, any future O10 write-up.
- **Partially resolves U07:** validation *methodology* is now frozen and
  ready to execute once a dataset is available. **Does NOT resolve access:**
  whether to request SWaT/iTrust access at all remains a separate, explicit,
  NOT YET APPROVED decision — do not conflate methodology approval with an
  access authorization.
- **Does NOT resolve:** `k` real-physics validation (still impossible on
  SWaT/WADI), `AttributionEngine`/O3 (blocked on a `PhysicsRule` that doesn't
  exist), the six-tag selection itself (blocked on the tag dictionary), and
  the WADI localization check (explicitly out of scope by E).

### D012 — SWaT.A1 six-tag mapping selected for the D011-B plumbing/proxy substitution
- **Date:** 2026-08-25
- **Decision:** The six SWaT.A1 tags relabeled onto the frozen six channel
  field names (D011 B) are:
  - `LIT101` → `temperature`
  - `AIT203` → `vibration`
  - `DPIT301` → `pressure`
  - `LIT401` → `humidity`
  - `AIT402` → `gas`
  - `PIT501` → `current`

  This is **exclusively** the plumbing/proxy substitution already defined by
  D011 B — **no claim of physical equivalence is made for any of these six
  pairings.** In particular: **`AIT402` measures aqueous
  Oxidation-Reduction-Potential (ORP) of the RO feed water — a dissolved
  water-chemistry property. It is NOT an ambient-gas or air-quality sensor,
  and must never be described as one in any report, log, or write-up.** The
  `gas` field name is a fixed software interface slot only.
- **Reason/evidence** (empirical, from the actual downloaded
  `SWaT_Dataset_Normal_v1.xlsx`/`SWaT_Dataset_Attack_v0.xlsx` files, not
  external literature):
  - All six tags: zero null/non-numeric/negative values in both files;
    confirmed present in both; strict temporal separation confirmed
    (`Normal_v1` ends 2015-12-28 09:59:59, `Attack_v0` begins 2015-12-28
    10:00:00, zero overlapping timestamps).
  - Pairwise correlation among the six selected tags (`Normal_v1`) stays
    below 0.5 for every pair; the closest is `LIT401`↔`PIT501` at +0.450.
  - `PIT502` was evaluated as a `gas`-slot candidate and **rejected**: a
    single 32,038-row exact-constant run in `Attack_v0` (7.12% of the file)
    overlaps 58.53% of all Attack-labeled rows — a blocking data-quality
    issue under the existing per-window min-max preprocessing (matches the
    flatness-artifact failure mode already recorded in `P2_RESUME.md` §3).
  - `AIT402` was chosen over runner-up `AIT502` (mutually correlated at
    0.98): `AIT402` shows a stronger empirical attack-shift score (17.8 vs.
    10.8), roughly double the in-attack-period variance (std 85.3 vs. 41.9
    within Attack-labeled rows) and mean separation (101.1 vs. 46.4), and
    remains highly dynamic (99.2% of its full value range) during the exact
    multi-hour shutdown window that disqualified
    `PIT502`/`FIT101`/`FIT201`/`FIT401` — none of which affects `AIT402`.
    Both correlate only moderately with fixed `AIT203` (0.606/0.563) and are
    otherwise clean against the other four fixed tags.
  - Both `AIT402` and `AIT502` show substantial "near-flat" 30-sample-window
    behavior under a tolerance-based (not exact-equality) flatness test
    (~91% and ~74% of `Attack_v0` respectively) — this reflects the
    slow-responding nature of chemical analyzer signals, not a
    frozen/pinned sensor, and is a concrete instance of the
    normalization-choice question `P2_RESUME.md` §3/§5 already defers to
    real-data evaluation (U07) — not a new, AIT402-specific defect, and not
    resolved by this decision; must be carried into the eventual harness
    documentation.
- **Affects:** the eventual `edge/eval/swat_eval.py` (not yet created — no
  adapter has been built as part of this decision).
- **Partially resolves D011 B:** the six-tag selection itself — the one item
  D011 explicitly listed as outstanding — is now resolved. **D011's own
  text is unchanged and remains fully authoritative** for every other
  point: proxy-only framing, `k` excluded from validation evidence,
  `AttributionEngine`/O3 deferred/blocked, WADI localization check rejected,
  strict temporal train/eval separation mandatory.
- **Does NOT resolve:** building the adapter/harness, running any
  evaluation, `k`/`AttributionEngine`/O3 validation (still blocked per D011
  C/D), or the still-open normalization-choice question the flatness
  findings above illustrate but don't settle.

### D013 — ChannelFlagPolicy redesign (Candidate B) + minimal provisional PhysicsRule; first formal P2 acceptance suite run
- **Date:** 2026-08-25
- **Decision:**
  1. **ChannelFlagPolicy's per-channel localization heuristic is redesigned
     ("Candidate B").** The original same-window, cross-channel
     highest-variance rule is replaced with a per-channel, own-baseline,
     two-sided empirical-CDF test: `fit()` learns each channel's OWN
     baseline distribution of window-variance from clean-baseline windows
     (same discipline as IF/`c`), and `flags()` flags a channel if its
     CURRENT window-variance is an outlier — high or low — relative to
     THAT channel's own historical distribution, never relative to other
     channels in the same window. Constructor parameter renamed
     `variance_factor` → `tail_fraction` (default 0.1; still arbitrary,
     provisional, U07-gated — not derived from real data).
  2. **A minimal, provisional `PhysicsRule` is implemented**
     (`TrendSignPhysicsRule`, `edge/anomaly/physics_rule.py`), reusing
     D010's current↔vibration trend-sign heuristic verbatim (no new
     physics, no new channel pair, no new tolerance) solely to unblock
     `AttributionEngine`'s wiring path. Before this, NO concrete
     `PhysicsRule` existed anywhere (D011 D), so `attribution=attack` was
     structurally unreachable in every case, everywhere. Scope is
     deliberately narrow: only ever names `current`/`vibration` as
     suspect (ties broken by which deviates further from its own fitted
     baseline); inherits `k`'s documented flat-trend blind spot (a
     zero-trend channel always "agrees", so a pure constant value can
     never trigger a violation).
  3. **The first-ever formal P2 acceptance-test suite**
     (`edge/tests/test_p2_acceptance.py`) was written and run against the
     PRD's literal Doc06 P2-ANOM-\*/P2-TRUST-\* table, using real
     (non-stub) components end-to-end on hardware-free simulator streams.
     10 of the 14 documented scenarios were attempted (P2-ANOM-S1 excluded
     — no adaptive/stealth injection type exists).
- **Reason:** Root-cause analysis (design-analysis-only pass, before any
  code changed) traced P2-ANOM-H2/H3 and part of P2-TRUST-H2's failures to
  one mechanism: per-window min-max normalization always rescales each
  channel to fill `[0,1]`, so a single-sample spike compresses the *other*
  29 samples toward one end (LOWERING that channel's own measured variance,
  the opposite of what the original "flag highest variance" rule expected),
  and a fully-inside constant-spoof window is exactly variance=0.0 — the
  most extreme possible low value. Reversing the rule's direction alone was
  analyzed and rejected: drift/ramp-shaped anomalies produce a variance
  signature close to ordinary noise, so a flipped rule would then prefer an
  unrelated, quieter channel over the genuinely drifting one. `AttributionEngine`
  was separately and completely blocked by the total absence of any
  `PhysicsRule` implementation, independent of ChannelFlagPolicy.
- **Evidence** (this session's own diagnostic → implementation → regression
  chain, not external literature):
  - Targeted regression (`test_policy.py`, `test_p2_acceptance.py`,
    `test_pipeline.py`, `test_swat_eval.py`, `test_physics_rule.py`, plus a
    full `pytest edge/` run): **327 passed, 4 failed, 2 skipped** — the 4
    failures are exactly the four pre-existing, unrelated ones (see status
    matrix in `P2_RESUME.md` §1); zero new regressions anywhere.
  - **P2-ANOM-H2 (spike): FAIL → PASS.** Confirmed mechanism: the spiked
    channel is now correctly identified as a low-variance outlier relative
    to its own baseline, instead of every *other* channel being flagged
    instead (as the original rule did).
  - **P2-TRUST-H2:** `gas`'s `channel_flags` true-rate rose from 13.3%
    (20/150 post-onset windows) to 68% (102/150) — a >5x improvement — but
    final trust still doesn't cross <0.4 within 3 windows. Root cause is
    now understood to have shifted: it is `h`'s own EMA speed (D009,
    GAMMA=0.95, ~13-window half-life) that caps how fast trust can fall,
    independent of ChannelFlagPolicy. This is a genuine tension between two
    separately-approved decisions (D009's deliberate slowness for
    collusion-resistance vs. this scenario's 3-window budget), not a defect
    in either — D009/GAMMA is explicitly UNCHANGED by this decision.
  - **P2-ANOM-H3 / P2-ANOM-E2: now runnable and PASS at their committed
    fixture seeds** — genuinely new capability (previously both were fully
    blocked, not just failing). Verified via explicit multi-seed sensitivity
    checks (not committed as separate tests) to be reliability-limited, not
    validated: H3 ≈4/8 seeds attack-attributed (~50%, driven by the onset
    transition window's spike-like shape interacting with the *other*
    paired channel's unrelated noise — the flat-trend blind spot only
    applies to fully-steady-state windows, not the transition into one);
    E2 ≈3/5 seeds attack-attributed (more reliable than H3 due to the
    deliberately-opposed-trend construction, still not deterministic). Both
    limitations are documented directly in the test file's own docstrings
    and assertion messages, not smoothed over.
  - **SWaT track: untouched.** `DECISIONS.md` D011/D012 and
    `edge/eval/swat_eval.py` are unmodified; `_NullPhysicsRule` remains
    exactly as before there, per D011 D (AttributionEngine explicitly
    blocked for the SWaT validation track — this decision does not
    reopen that). No SWaT experiment was run as part of D013.
- **Affects:** `edge/anomaly/policy.py` (rewritten), `edge/anomaly/physics_rule.py`
  (new), `edge/tests/{test_policy,test_physics_rule,test_p2_acceptance}.py`,
  `edge/eval/swat_eval.py` (plumbing only — threads the now-fittable
  `flag_policy` through `fit_baseline`/`build_pipeline`; no change to what
  it reports or how it's used).
- **Partially resolves U02:** a `PhysicsRule` now exists, even if minimal
  and narrow — `attribution=attack` is structurally reachable for the
  current/vibration pair where before it was unreachable everywhere.
  ChannelFlagPolicy's own long-standing "needs multivariate per-feature
  attribution, UNDECIDED" status (`CURRENT_STATE.md`/`TODO.md`, pre-D013) is
  now RESOLVED (provisional) — Candidate B is a genuine non-cross-channel
  redesign, though still heuristic and untuned.
- **Does NOT resolve:** real physics/accuracy validation for either
  `tail_fraction` or the trend-sign heuristic (both remain U07-gated); O3
  (≥85% attribution accuracy) — still structurally unreachable for 4 of 6
  channels (no rule defined for them) and only chance-level (~50–60%) for
  current/vibration; P2-ANOM-H1/E1 (IF/threshold/normalization clean-FP and
  oscillation — a separate, untouched root cause); P2-TRUST-H1 (`c`'s
  rank-based noise); P2-TRUST-H2's remaining gap (now identified as `h`'s
  GAMMA/window-budget tension, D009 — explicitly not touched by D013);
  P2-ANOM-S1 (no adaptive/stealth injection type exists).
- **Status:** implemented and tested (see Evidence); lint/format clean;
  **uncommitted** as of this entry — commit pending explicit approval, per
  the established implement → test → report → commit-on-approval sequence.

### D014 — Broader `PhysicsRule` coverage: scoping review concludes no defensible expansion now; current↔temperature is the sole future candidate, hardware-gated
- **Date:** 2026-08-30
- **Decision:** Following D013's identification of a broader `PhysicsRule` as
  the one remaining mandatory implementation blocker for O3 progress
  (`P2_RESUME.md` §7a), a scoping review was conducted for the four channels
  `TrendSignPhysicsRule` does not cover (`temperature`, `pressure`,
  `humidity`, `gas`). Conclusion: **no channel coverage is added.**
  `TrendSignPhysicsRule` remains exactly as D013 defined it (current↔vibration
  only, no new code). Per-channel findings:
  - **`pressure`:** REJECTED. Reopening current↔pressure — the pair FR-A2
    and the PRD demo script (§18) literally name — would require overturning
    D010's already-recorded finding that BMP180 reads atmospheric pressure
    only, not water-line/discharge pressure. Not revisited; D010 stands
    unchanged.
  - **`humidity`:** REJECTED. The PRD's own "Design integrity note" (§12)
    and risk R6 explicitly require temperature (DS18B20) and humidity
    (DHT22) to remain uncorrelated in the trust engine, specifically so the
    cross-sensor correlation term cannot be trivially satisfied by two
    related channels from the same physical process. Any humidity-based
    physics rule would contradict a stated PRD design requirement, not
    merely lack evidence.
  - **`gas`:** REJECTED. No documented mechanical, electrical, or thermal
    linkage to any other channel exists in the PRD/TRD. MQ-135 is explicitly
    framed as an indicative air-quality proxy (VOC/CO2, not H2S), with no
    basis for any coefficient or tolerance. Implementing a rule here would
    be fabricated physics.
  - **`temperature`:** DEFERRED, not rejected. Motor/bearing heat generation
    under load (I²R losses) is a textbook-plausible physical link to
    `current`, and nothing in the PRD forbids it (unlike humidity). However,
    no coefficient, lag model, or threshold exists in any project document,
    and no bench data has ever been collected to characterize it — thermal
    response also operates on a materially different timescale than the
    near-instantaneous mechanical coupling `k`/`TrendSignPhysicsRule` already
    exploit. **Marked as a future candidate, gated on real bench data
    collection** (requires the Pi/rig, not available in this environment) —
    not to be implemented from the simulator, which generates all channels
    as independent Gaussians with no real correlation to validate against
    (same limitation D010 already recorded for current↔vibration).
- **Reason:** Continues the project's established discipline (D010, D013) of
  never inventing a physics relationship, threshold, or coefficient without
  either explicit documentation or real data to justify it. Two of the four
  channels are foreclosed by existing decisions/PRD text, not merely
  under-evidenced; a third has no plausible basis at all; only one is left
  open, and only as a future, hardware-gated candidate.
- **Affects:** `edge/anomaly/physics_rule.py` (unchanged), `edge/anomaly/attribution.py`
  (unchanged), O3 acceptance status (`P2_RESUME.md` §1a/§7a).
- **Does NOT resolve:** U02 (real physics validation beyond current/vibration —
  still open, now explicitly scoped to "current↔temperature, bench-data-gated"
  as its only live candidate). O3 (≥85% attribution accuracy) — remains
  **NOT ACHIEVABLE**, and this decision does not change that: even a
  validated current↔temperature rule would cover at most 3 of 6 channels,
  leaving pressure/humidity/gas permanently unattributable as "attack" under
  this scope.
- **Does NOT change:** D009, D010, D011, D012, D013, or `AttributionEngine`'s
  single-`PhysicsRule` architecture. No code was modified by this decision.
- **Status:** documentation-only; no implementation performed or authorized
  by this entry.

### D015 — P2-TRUST-H2 formally documented as a structural limitation; GAMMA/D009, D010, and λ left unchanged
- **Date:** 2026-08-30
- **Decision:** Following the D009/D010-scoping analysis of P2-TRUST-H2
  (spoofed sensor, "trust < 0.4 within ≤3 windows"), **no code or parameter
  is changed.** `D009` (`h`'s GAMMA=0.95, H_INIT=1.0, EMA structure) and
  `D010` (`k`'s current↔vibration formula and its `k=1.0` default for
  non-paired channels) both remain exactly as approved. `λ=0.7` (still
  formally "PENDING approval" per U01, never itself a numbered decision)
  is also left untouched. P2-TRUST-H2 is reclassified from an open,
  GAMMA-attributed gap to a **formally documented structural limitation**.
- **Root cause (established this pass, not previously documented at this
  precision):** a three-way interaction, not a single-parameter gap:
  1. The committed P2-TRUST-H2 acceptance test uses `ConstantSpoof` — a
     constant, zero-trend injection.
  2. `k`'s trend-sign rule (D010) treats a zero-trend channel as always
     "agreeing" (a documented, pre-existing blind spot: *"One rising + one
     flat trend passes... a known limitation"*, `k_correlation.py`). A flat
     spoof therefore never drives `k` below `1.0` — true for the tested
     non-paired channel (`gas`, where `k=1.0` is D010's permanent default
     for `temperature`/`pressure`/`humidity`/`gas`), and would be equally
     true for `current`/`vibration` under the same flat-value attack shape,
     since the blind spot is in the rule itself, not the channel.
  3. Since `g = 0.4c + 0.3k + 0.3h` and `k` stays pinned at `1.0`, `g` is
     structurally floored at `0.3` (`= W_CORRELATION · 1.0`) regardless of
     how low `c` or `h` fall — even in the limiting case where `c=0`
     (confirmed to occur immediately, not gradually, for the committed
     spoof magnitude) and `h→0`.
  4. Diagnostic replay (this pass, read-only, imports only existing
     unmodified `edge.trust.*` modules; not committed to the repo) confirms
     this floor's consequence directly: with `h` hypothetically collapsed
     to `0` instantly on window 1 — i.e. **GAMMA/D009 entirely removed
     from the equation** — trust still does not cross `0.4` until window 5
     after onset, not window 3. Only when `k` is *also* hypothetically
     forced to `0` (a change D010 explicitly does not make for any
     channel under a flat-value attack) does the trust trace reproduce
     D009's own approval-trail arithmetic (`T_3 = λ³ = 0.343 < 0.4`,
     `edge/trust/beta.py` docstring) at exactly window 3.
  5. Conclusion: **D009's own justification for meeting the ≤3-window
     criterion was implicitly valid only for an attack/channel combination
     where `g` can reach `0`** — which a flat/constant spoof under D010's
     current `k` rule never allows, on any channel. GAMMA is a secondary,
     compounding factor, not the binding constraint.
- **Why changing GAMMA alone cannot solve H2:** demonstrated directly by
  the diagnostic above — removing GAMMA's slowness entirely (instant `h`
  collapse) still leaves `g` floored at `0.3` by `k`, and still misses the
  3-window budget by ~2 windows. Any fix would have to touch `k`'s
  non-paired default or its flat-trend handling (D010) as well, and/or
  `λ` — not GAMMA in isolation.
- **Why D009 and D010 remain unchanged:** Both have documented,
  deliberately-chosen rationale that this analysis does not overturn.
  D009's slow GAMMA exists specifically to resist a collusive attacker
  attempting to hold full trust (see next bullet). D010's `k=1.0`
  non-paired default and its flat-trend blind spot were explicitly left
  unfixed pending real data (*"Do not introduce an epsilon threshold to
  'fix' this without data-backed justification"*, `k_correlation.py`) —
  this decision does not manufacture that justification. No new bench or
  dataset evidence has arrived since D009/D010 were approved; nothing here
  changes the basis either was made on.
- **Impact on P2-TRUST-S1 / collusion resistance:** **None — fully
  preserved.** P2-TRUST-S1 continues to PASS unmodified. GAMMA's slowness
  is the entire mechanism D009 relies on to prevent a collusive two-channel
  attack from holding full trust; leaving it untouched keeps that guarantee
  intact. Any future attempt to close H2 by speeding up `h`/`λ` would
  directly erode this same protection — a real trade-off, not a free
  improvement, and is exactly why reopening D009/D010 together was not
  chosen.
- **What remains open for future real-hardware validation:** whether a
  different `GAMMA`, a faster `λ`, or a revised `k` rule (addressing the
  flat-trend blind spot or the non-paired-channel default) could close
  P2-TRUST-H2 without materially weakening P2-TRUST-S1 — answerable only
  with real bench data characterizing actual attack cadence and false
  collusion risk, none of which exists today. Also open: whether a
  non-flat injection shape for this specific acceptance scenario would be
  more representative of a real spoofing attack than `ConstantSpoof` — a
  test-design question, not a production-code one, and not decided here.
- **Affects:** `P2_RESUME.md` §1a/§7a (P2-TRUST-H2 status), `TODO.md`
  (validation-limitations list), `CURRENT_STATE.md` (Known blockers / U01
  line). No production code (`edge/trust/*`, `edge/anomaly/*`) or tests
  are affected.
- **Does NOT resolve:** U01 (`λ` remains PENDING, unrelated to this
  decision). Does NOT claim P2-TRUST-H2 passes, and does NOT claim
  **O4/AC2** (PRD's "<0.4 within ≤3 windows" / "attack detected, trust
  drops <0.4 within ≤3 windows") is satisfied — both remain explicitly
  NOT achieved for this scenario, honestly documented as a limitation, not
  implied as passing or waived.
- **Does NOT change:** D009, D010, D011, D012, D013, D014, `λ`, or any
  code in `edge/trust/*` / `edge/anomaly/*`. Documentation-only.
- **Status:** documentation-only; no implementation performed or
  authorized by this entry.

### D016 — U03: prognosis and digital-twin implemented as separate models; twin is channel-agnostic
- **Date:** 2026-08-31
- **Decision:** Prognosis (FR-M1–3: health state + failure-ETA) and the
  digital-twin (FR-H2: isolated-channel reconstruction + uncertainty) are
  implemented as **two separate models**, not one shared multi-task LSTM.
  The digital-twin is a single **channel-agnostic** model — it takes the
  available channels plus an indicator of which channel is missing, and
  reconstructs that one channel — rather than one model per channel. TRD
  §02.6's singular `lstm.pt` naming is treated as illustrative
  folder-structure prose, not a binding technical requirement; storage may
  use e.g. `lstm_twin.pt` + `lstm_prognosis.pt` (exact names TBD at
  implementation time).
- **Reason:** The digital-twin can be developed and hardware-free-tested
  now via self-supervised masking on the existing D005/D008 simulator
  streams; prognosis cannot, since no degradation-trajectory training data
  exists yet (D017/U04). Separate models decouple the two tasks so the
  twin's development is not gated on prognosis's unresolved data question,
  and avoid an untested multi-task negative-transfer risk with no data
  currently available to evaluate it either way. A channel-agnostic twin
  avoids a 6× architecture/storage/training surface with no PRD/TRD
  requirement forcing per-channel models.
- **Affects:** future `edge/pipeline/prognosis(lstm)`,
  `edge/pipeline/self_heal`, `edge/models/` (none of these exist yet — no
  code created by this decision).
- **Does NOT resolve:** U04 (training-data source — see D017), U05
  (`divergence_threshold` + substitution uncertainty-cap values), U06 (RL
  reward shaping), the digital-twin's uncertainty-estimation method
  (FR-H2), or any model architecture detail — no layer sizes,
  hyperparameters, or loss functions are specified or implied by this
  decision.
- **Does NOT change:** D009–D015, or any existing P2 code/tests.
- **Status:** documentation-only; no implementation performed or
  authorized by this entry. No P3 code exists in this repo.

### D017 — U04: synthetic simulator data approved for initial P3 development; not a real-world validation substitute
- **Date:** 2026-08-31
- **Decision:** Synthetic (simulator-generated) data is approved as the
  data source for **initial, hardware-free P3 development and testing
  only** — no Pi/rig is available. This is explicitly scoped to
  plumbing/logic development and testing; it must **never** be described
  as validating real-world prognosis accuracy or real-world digital-twin
  reconstruction accuracy. The existing D005/D008 simulator (`simulator/`)
  plus P2's injection framework (`edge/injection/`) provide the **initial
  synthetic data source** for hardware-free digital-twin development (e.g.,
  self-supervised mask-and-reconstruct training/testing). This is a
  statement of availability, not a claim that this data is proven
  sufficient or adequate for useful/real-world reconstruction accuracy —
  that adequacy remains **unvalidated and untested**. No new
  synthetic-data-generation capability is created or specified by this
  decision. **Prognosis (FR-M1–3) training remains blocked**: no synthetic
  degradation-trajectory generator exists, and this decision does not
  create, specify, or approve one — that remains a separate, later scoping
  step (or real bench data becomes available first).
- **Reason:** Mirrors the discipline already established for P2
  ("foundation/plumbing complete ≠ validation complete", `P2_RESUME.md`)
  and D005's existing precedent for simulator-based non-physical work,
  without extending that precedent to license real-accuracy claims neither
  D005 nor the simulator's own design were ever meant to support.
- **Affects:** future hardware-free digital-twin development/testing only;
  explicitly does not affect prognosis, which stays blocked pending its own
  data decision.
- **Does NOT resolve:** whether bench data is ever required before any P3
  acceptance claim; the design or existence of any degradation-trajectory
  generator; U03 (see D016), U05, U06, or the digital-twin's
  uncertainty-estimation method.
- **Does NOT change:** D005, D008, or any other existing decision; no code,
  tests, or the existing simulator are modified by this entry.
- **Status:** documentation-only; no implementation performed or
  authorized by this entry. No P3 code exists in this repo.

### D018 — P3 digital-twin substitution/divergence behavioral design (Interpretation A + five sub-decisions)
- **Date:** 2026-08-31
- **Decision:** Building on D016 (separate, channel-agnostic digital-twin
  model) and D017 (synthetic data approved for initial hardware-free
  development only), the following behavioral design is adopted for the
  FR-H1–H4 isolation/substitution/divergence path. **No numeric threshold,
  uncertainty-cap value, or uncertainty-estimation method is chosen by this
  entry.**

  **Foundation — divergence semantics ("Interpretation A"):** When a
  channel is isolated, its raw reading continues to be sampled and remains
  available, but is excluded/down-weighted from trusted fusion (FR-H1).
  FR-H3's "real-vs-twin divergence" is measured between the digital-twin's
  reconstruction and that isolated channel's continuing raw reading.
  **This divergence check is an explicit backstop/anomaly signal — it is
  NOT proof that the twin's reconstruction is correct, and it is NOT an
  independent trusted reference**, since no redundant per-channel
  instrumentation exists in the current hardware (TRD BOM: one physical
  sensor per channel). The circularity/gameability risk this creates is
  the one the PRD's own risk register already names (R3: *"Virtual
  substitution is circular / gameable"*) — this decision does not resolve
  that risk, only adopts the interpretation the PRD's test cases
  (P3-HEAL-S1/S2) and available architecture actually support, with the
  risk explicitly carried forward, not hidden.

  1. **Divergence computation form:** a fit-time z-score-based
     magnitude/distance representation (reusing the same
     fit-on-clean-baseline-mean/std discipline already used by
     `ConsistencyProvider`/`TrendSignPhysicsRule`), not per-window min-max
     normalization (already found to be a source of excess noise, H1/E1
     analysis) and not an empirical-CDF/rank score (already found to be
     diffuse-under-null, unsuited to representing a magnitude of physical
     disagreement, TRUST-H1 analysis). Unitless and cross-channel
     comparable by construction. **No numeric `divergence_threshold` is
     chosen — remains data-gated (U05).**
  2. **Recovery:** a previously isolated channel may be re-admitted to
     trusted fusion when its P2 trust score returns to `TRUSTED_MIN`
     (0.7), the same, already-frozen boundary FR-T3 already uses to
     classify a channel as "Trusted." No new hysteresis, window count, or
     threshold is introduced — the existing three-band structure
     (Malicious <0.4 / Suspicious 0.4–0.7 / Trusted ≥0.7) already provides
     the buffer between whatever triggered isolation and this
     re-admission point.
  3. **60-second substitution expiry:** if `substitution_max_seconds`
     (already 60, Doc05 default) expires without the channel having
     safely recovered per (2), the system escalates to Safe Pump-Stop.
     This is an explicit safety-policy decision filling a gap FR-H3 does
     not itself specify (FR-H3's escalation clause is grammatically tied
     only to divergence exceeding its threshold) — not a claim the PRD
     already mandated this.
  4. **Uncertainty interface:** the raw numeric uncertainty estimate
     (FR-H2) stays edge-internal. The frozen `DecisionMessage` contract
     (`backend/app/schemas/contracts.py`) is not modified. P3-HEAL-E1's
     "confidence flagged high; alert raised" is satisfied via the existing
     `alerts` mechanism (Doc05: `type`/`channel`/`message`/`reason`),
     using the existing `'system'` value of the `type` ENUM, unless
     implementation later proves an enum extension is technically
     required — no new alert type is introduced now.
  5. **Cycle sequencing:** within each processing cycle, P2 (trust/
     isolation determination) runs first; P3 (substitution + divergence
     check for isolated channels) runs second, consuming P2's output
     without modifying P2's internals. The isolated channel's raw value
     is monitoring-only for the duration of isolation: it feeds the
     divergence check and nothing else — it is never fed back into the
     trusted-fusion/prognosis path (FR-M3).
- **Reason:** Closes the behavioral design questions the U05 scoping
  analysis (this session) found necessary before any divergence/
  substitution code could be written, using in every case either an
  already-frozen project constant (`TRUSTED_MIN`, `substitution_max_seconds`),
  an already-established computational pattern (fit-time z-score, reused
  from `c`/`k`'s own baseline-fitting discipline), or an already-existing
  mechanism (the `alerts` table), rather than inventing new infrastructure.
  Explicitly declines to resolve the two genuinely data-gated numeric
  values or the uncertainty-estimation method, consistent with this
  project's established discipline of not inventing thresholds/formulas
  without real data (D010, D013, D017).
- **Affects:** future `edge/pipeline/self_heal`, future digital-twin/
  divergence-check code (none exists yet — no code created by this
  decision), Doc05's `alerts` usage pattern (no schema change),
  `edge/trust/beta.py`'s `TRUSTED_MIN` (reused, not modified).
- **Does NOT resolve:** the numeric `divergence_threshold` value, the
  numeric uncertainty-cap value, or the uncertainty-estimation method
  (FR-H2) — all remain explicitly open (U05 narrows to exactly these two
  numeric values; the uncertainty method remains a separate, unnumbered
  open item, unaffected by this decision).
- **Does NOT change:** D005, D009–D017, `beta.py`'s `TRUSTED_MIN`/
  `MALICIOUS_MAX` values, the `DecisionMessage` contract, or any existing
  code/tests. Documentation-only.
- **Status:** documentation-only; no implementation performed or
  authorized by this entry. No P3 code exists in this repo.

### D019 — P3 uncertainty method: deterministic elapsed-substitution-time proxy (provisional)
- **Date:** 2026-08-31
- **Decision:** The digital-twin's uncertainty estimate (FR-H2) is
  provisionally implemented as a deterministic proxy based on elapsed time
  since the **current** substitution episode began, with the following
  semantics:
  - Starts at its minimum when substitution begins.
  - Non-decreasing for the duration of that substitution episode.
  - Bounded relative to the existing `substitution_max_seconds` (60,
    Doc05 default, D018) — not a second, competing time constant.
  - Resets when a new substitution episode begins (a direct consequence
    of D018's recovery rule: once trust returns to `TRUSTED_MIN`,
    substitution ends, and any later isolation begins a new episode).
  - Explicitly a **provisional safety/confidence proxy — NOT a
    statistically calibrated estimate of reconstruction error**, and not
    claimed to be one.
  - Reconstruction-stability and D018's divergence signal are explicitly
    **NOT** added as additional uncertainty inputs at this stage — the
    method is kept minimal, deterministic, and single-signal.
  - Remains edge-internal; no `DecisionMessage` contract change
    (consistent with D018).
  - The exact time→uncertainty **scaling formula** (e.g. linear or
    otherwise) is **NOT** chosen by this entry and remains open.
  - The numeric **uncertainty-cap** and **`divergence_threshold`** are
    **NOT** chosen by this entry.

  Also approved: the P3-HEAL-E1 wording clarification — **"Uncertainty
  flagged high (nearing cap); alert raised"** — replacing the ambiguous
  "Confidence flagged high; alert raised," to avoid reading the outcome as
  "confidence is high" (self-contradictory alongside raising an alert for
  approaching a limit).
- **Reason:** Closes FR-H2's "attached uncertainty estimate" requirement
  with the smallest defensible hardware-free method identified this
  session — reusing the already-approved `substitution_max_seconds`
  reference point (D018) rather than introducing a competing time
  constant, adding no new model architecture/training objective (unlike a
  learned interval), and no rank/CDF scoring (which D018's own reasoning
  already disfavored for a magnitude-style bound). Explicitly provisional,
  consistent with this project's established pattern (D013's
  `TrendSignPhysicsRule`) of shipping a minimal, honestly-labeled
  placeholder pending real data or a future, more principled method
  (PRD §22's deferred Bayesian/ensemble approaches remain available
  later).
- **Affects:** future `edge/pipeline/self_heal` (does not exist yet — no
  code created by this decision); the `alerts`-mechanism usage already
  established by D018 (wording clarification only, no schema change, no
  new alert type).
- **Does NOT resolve:** the time→uncertainty scaling formula, the numeric
  uncertainty-cap value, or `divergence_threshold`'s numeric value — all
  three remain open. U05 narrows no further, numerically, than D018 already
  narrowed it — still exactly the same two numeric values.
- **Does NOT change:** D005, D009–D018, the `DecisionMessage` contract, or
  any existing code/tests. Documentation-only.
- **Status:** documentation-only; no implementation performed or
  authorized by this entry. No P3 code exists in this repo.

### D020 — U05: uncertainty-cap value + elapsed-time→uncertainty scaling formula (provisional policy)
- **Date:** 2026-08-31
- **Decision:** Resolves the two items D019 explicitly left open, plus one
  related gap identified during this session's scoping pass (the
  uncertainty output domain, never previously declared anywhere).
  1. **Scaling formula:** linear — `f(x) = x`, where `x` is the already-
     implemented, bounded elapsed-substitution-time fraction in [0,1]
     (`ElapsedTimeUncertaintyProxy`'s existing `fraction = min(elapsed_
     seconds / substitution_max_seconds, 1.0)`, unchanged). No new time
     constant, no additional signal — reuses exactly the fraction D019
     already established.
  2. **Uncertainty output domain:** [0,1] is hereby a SPECIFICATION
     REQUIREMENT for the project's approved scaling function, consistent
     with this codebase's existing `Score`-style convention for
     trust/severity. The approved `f(x)=x` (point 1) satisfies this by
     construction, since its input is already bounded to [0,1] by the
     existing fraction clamp — but this is a property of the specific
     approved function, not a guarantee provided by
     `ElapsedTimeUncertaintyProxy` or the generic `ScalingFn` Protocol
     itself, which remains an unconstrained injectable callable with no
     runtime bound-checking on its return value. A non-conforming
     scaling_fn could still be injected in code without error; this
     decision fixes what the project's real scaling function should be
     and what range it must produce, not what the API mechanically
     enforces.
  3. **`uncertainty_cap`:** 0.8, expressed in the uncertainty proxy's own
     output domain (not seconds — keeps the three signals independent, as
     already established). With the existing `substitution_max_seconds=
     60` default (D018 pt.3, unchanged) and linear scaling, the alert
     fires once ~80% of the substitution budget has elapsed (~48s),
     strictly before the 60s hard expiry (fraction=1.0) — preserving the
     intended severity ordering: a softer, earlier "nearing cap" alert
     (P3-HEAL-E1) before the harder 60s escalation to Safe Pump-Stop
     (D018 pt.3).
  4. **`uncertainty_cap` remains a required constructor argument on
     `SelfHealOrchestrator`, with no default introduced.** This decision
     fixes what the value should be; it does not change how it is
     supplied. No hardcoded default is added anywhere — a real value only
     reaches the orchestrator when an actual caller explicitly passes
     `uncertainty_cap=0.8` (test fixtures are unaffected either way).
- **Reason:** D019's proxy was explicitly designed as a deterministic,
  non-statistical safety/confidence signal, not a calibrated estimate of
  reconstruction error — so no amount of real bench data would make one
  scaling shape or cap value more "correct" than another; both are
  legitimately operational/policy choices, not data-gated ones
  (established by this session's scoping pass). Linear is the smallest,
  most defensible shape: it introduces no additional assumption about the
  *rate* of confidence decay beyond "proportional to elapsed time," unlike
  a curved (quadratic/exponential) or step alternative, each of which
  would encode a specific, undocumented belief about how risk should be
  communicated. 0.8 is a round policy value that leaves a 20%
  advance-warning margin (~12s) before the hard 60s escalation.
- **Affects:** any future caller that constructs a `SelfHealOrchestrator`
  for real use (none exists yet — the P2→P3 cycle-wiring caller remains
  blocked on the RL agent/fallback, FR-RL2/FR-RL4). Narrows U05 to exactly
  one remaining open item: `divergence_threshold`.
- **Does NOT resolve:** `divergence_threshold`'s numeric value — remains
  fully open and data-gated (needs real reconstruction-error and
  fault/attack-separation statistics; unaffected by this decision). Does
  NOT resolve where `uncertainty_cap` should live structurally (e.g.,
  whether it deserves its own Doc05 `thresholds` schema column the way
  `divergence_threshold` already has one — Doc05 currently has no column
  for it at all, a gap noted in this session's scoping pass but not
  addressed here). Does NOT resolve U06 (RL reward shaping) or anything
  about prognosis/RL/dry-run.
- **Does NOT change:** `edge/pipeline/uncertainty.py`,
  `edge/pipeline/self_heal.py`, or any other existing code or test — this
  is a documentation-only decision. `ElapsedTimeUncertaintyProxy.
  scaling_fn` and `SelfHealOrchestrator.uncertainty_cap` remain required
  constructor arguments with no default in the actual code; this decision
  does not modify either class, does not add runtime validation/
  enforcement of the [0,1] output domain to `ScalingFn`/
  `ElapsedTimeUncertaintyProxy`, and does not introduce a default.
  D016–D019 unchanged.
- **Status:** documentation-only; no implementation performed or
  authorized by this entry. No code or test file is created or modified
  by this decision.

### D021 — U04 (prognosis): PRONOSTIA/FEMTO adopted as initial external prognosis training/validation dataset (methodology-scoped, not pump-validated)
- **Date:** 2026-08-31
- **Decision:** The PRONOSTIA/FEMTO bearing dataset (IEEE PHM 2012 Prognostic
  Challenge, hosted at the NASA Prognostics Center of Excellence Data Set
  Repository; origin: Nectoux et al., "PRONOSTIA: An Experimental Platform
  for Bearings Accelerated Life Test," IEEE PHM 2012) is adopted as the
  initial external research/training dataset for FR-M1/M2 prognosis
  development. It contains real rolling-bearing run-to-failure trajectories
  (17 experiments across 3 operating conditions; 6 full run-to-failure
  "learning set" + 11 truncated "test set") with genuine vibration
  (twin-accelerometer, 25.6kHz) and temperature (PT-100, 10Hz) degradation
  signals, run to actual physical failure.

  This dataset's purpose is exclusively to validate the prognosis training
  pipeline and LSTM methodology (windowing, training loop, loss convergence,
  RUL-labeling technique) against real degradation trajectories. **It is NOT
  evidence that the resulting model, or any model this project trains, is
  accurate for this project's actual pump.**

  Vibration and temperature may be treated ONLY as same-failure-mode-class
  proxies for pump-bearing degradation (the physical intuition: bearing wear
  raising vibration amplitude and temperature is the same failure-mode class
  in PRONOSTIA's test rig and in a pump's own bearings) — not as the same
  system, not as a validated transfer, not as physical equivalence beyond
  that narrow same-class relationship.

  Pressure, humidity, gas, and current are **NOT validated by this dataset**
  in any respect and must never be described as trained, validated, or
  even exercised against real degradation data as a result of this
  decision. No channel-by-channel physical equivalence between PRONOSTIA's
  sensors and this project's six channels is assumed or implied beyond the
  single, explicitly approved vibration/temperature same-failure-mode-class
  proxy relationship stated above.

  Real pump/bench validation remains required before any FR-M1/M2
  acceptance claim — this decision does not reduce or substitute for that
  requirement in any way.

  This decision explicitly does NOT authorize using SWaT, the P2 Drift/
  RampFDI injection framework, or the existing D005/D008 simulator as a
  degradation-data source; none of those are degradation data and none are
  affected by this entry.

- **Reason:** Of the public candidates researched (NASA C-MAPSS turbofan,
  PRONOSTIA/FEMTO bearing, Kaggle "Pump Sensor Data," MetroPT-3),
  PRONOSTIA offers the narrowest, most physically defensible proxy claim
  available without inventing a pump-equivalence mapping: bearings are a
  real component class present inside pumps, and vibration/temperature are
  the literal physical channels that class of degradation would move,
  unlike C-MAPSS (turbofan, zero shared channel types) or the Kaggle/
  MetroPT candidates (undocumented sensor semantics or license/provenance
  gaps respectively). This mirrors D011/D012's own precedent of adopting an
  external dataset under an explicitly scoped, non-equivalence claim.

- **Affects:** future prognosis training/experimentation work only
  (`edge/models/lstm_prognosis.py`'s existing untrained architecture skeleton
  is unaffected — no code, weights, or training run is created by this
  decision). Does not touch any existing P2/P3 production code, tests, or
  the existing digital-twin work.

- **Does NOT resolve:** HealthState threshold/band definitions, failure_eta
  horizon/units, loss function, optimizer, or any other still-open
  prognosis specification item (see D016's own disclaimer, unchanged). Does
  NOT resolve how PRONOSTIA's 25.6kHz/10Hz sampling maps onto this
  project's 1Hz/30-sample window structure. Does NOT resolve how the other
  four channels (pressure, humidity, gas, current) are represented during
  any PRONOSTIA-based training run for architecture-shape compatibility —
  this remains a fully separate, open modeling/data-mapping decision, and
  no treatment (zero-filling, a reduced-channel architecture variant, or
  any other approach) is chosen, implied, or recommended by this entry.
  Does NOT resolve U06 (RL) or U05's remaining `divergence_threshold` value.

- **Does NOT change:** D016, D017 (this is precisely the "separate, later
  scoping step" D017 explicitly declined to make — D017's own text and
  scope are unmodified by this entry), D018, D019, D020, or any existing
  code/tests. No dataset is downloaded, no training is performed, and no
  file besides this entry is created or modified by this decision.

- **Status:** documentation-only; no implementation, download, or training
  performed or authorized by this entry.

### D022 — PRONOSTIA input-representation mechanics: temperature downsampling, vibration burst summary, and missing-vibration indicator (narrow, mechanism-only)
- **Date:** 2026-08-31
- **Decision:** Building on D021 (PRONOSTIA/FEMTO adopted as an external
  vibration+temperature methodology-validation dataset only), this entry
  resolves exactly three narrow representation-mechanics choices needed to
  convert PRONOSTIA's actual raw structure into inputs the existing
  prognosis skeleton can consume:

  1. **Temperature downsampling (10Hz → 1Hz):** a 1-second block mean of
     the actually-measured 10Hz samples. Uses 100% of the real measured
     data (no discarded samples), introduces no filter/cutoff parameter.

  2. **Vibration burst summary:** each real ~0.1s vibration burst is
     collapsed to one scalar via RMS of the per-sample Euclidean magnitude,
     `sqrt(horizontal_i^2 + vertical_i^2)`, computed across the burst's
     samples. No interpolation of vibration across the ~10s silent gaps
     between bursts — a burst's summary value exists only at the timestep
     where a real burst actually occurred.

  3. **Missing-vibration indicator:** `trust=0` is explicitly NOT reused to
     represent an absent vibration observation — `SelfHealOrchestrator`'s
     existing trust mechanism applies one scalar per channel across an
     entire window (`trust[ch].trust`), not per-timestep, so it cannot
     mechanically distinguish "observed with low confidence" from "no
     observation exists" without conflating two different quantities.
     Instead, one explicit per-timestep `vibration_observed` indicator is
     added: `1.0` at timesteps where a real burst landed, `0.0` elsewhere;
     the vibration value itself is `0.0` at unobserved timesteps. This
     mirrors the existing masked-channel-indicator precedent already used
     by `edge/models/lstm_twin.py`'s `build_masked_input` (zero the value,
     flag it explicitly) rather than inventing a new mechanism.

     This widens the prognosis input contract from `len(CHANNELS)` to
     `len(CHANNELS)+1` scalars per timestep. **The LSTM itself is NOT
     redesigned:** it remains the single-layer, unidirectional encoder with
     the same two independent output heads (health 3-way classification,
     failure_eta scalar regression) approved earlier this session — only
     the per-timestep input WIDTH changes, not the network's depth,
     directionality, or head structure.

- **Reason:** Each choice is the smallest defensible option that uses only
  real measured data without interpolation or fabrication: block-mean and
  RMS are standard, parameter-free (or minimally-parameterized) summaries
  rather than a feature-engineering system; the observed-indicator reuses
  an already-established project pattern (the twin's masking indicator)
  instead of overloading `trust`'s existing, different meaning (confidence
  in a reading's genuineness, not whether a reading exists at all).

- **Affects:** the not-yet-implemented PRONOSTIA-to-prognosis input-building
  function (a future analogue to `build_trust_weighted_input`) and, when
  implemented, `edge/models/lstm_prognosis.py`'s `_LSTMPrognosisNet.
  __init__`'s `input_size` (from `len(CHANNELS)` to `len(CHANNELS)+1`). No
  code or test file is created or modified by this entry itself.

- **Does NOT resolve:** the four non-covered channels (pressure, humidity,
  gas, current) — they remain entirely unresolved; no zero-filling,
  synthesis, or any other treatment is chosen, implied, or assumed by this
  entry. Does NOT choose HealthState thresholds/band definitions. Does NOT
  choose failure_eta horizon or units. Does NOT choose loss function,
  optimizer, or any training hyperparameter. Does NOT define or authorize
  any prognosis acceptance metric. Does NOT touch RL/U06. Does NOT create
  any pump-validation claim — D021's own scope (methodology/training-
  pipeline validation only, vibration+temperature as a same-failure-mode-
  class proxy, real pump/bench validation still required) is entirely
  unchanged by this entry. **This entry does not authorize training** —
  it resolves representation mechanics only.

- **Does NOT change:** D016, D017, D018, D019, D020, D021 — all unchanged,
  D021 in particular unaffected in scope or wording. No existing code or
  test file is modified by this entry.

- **Status:** documentation-only; no implementation, preprocessing,
  dataset-loader, training, or test code is created or authorized by this
  entry.

### D023 — PRONOSTIA data-quality treatment: three subtractive exclusion rules (no fabrication, no reconstruction)
- **Date:** 2026-08-31
- **Decision:** Building on D021 (PRONOSTIA/FEMTO adopted as an external
  vibration+temperature methodology-validation dataset only) and D022
  (temperature block-mean, vibration RMS, missing-vibration indicator),
  this entry authorizes exactly three empirically verified, purely
  subtractive treatments for the raw-data quality problems found by the
  full 17-bearing audit:

  1. **Exclude bearings with zero temperature files entirely:**
     `Bearing2_2`, `Bearing3_2`, `Bearing1_3`, `Bearing2_3`, `Bearing2_6`.
     These bearings have no temperature data whatsoever; since D022's
     representation uses temperature as the defining 1Hz clock, there is
     no legitimate way to place these bearings' vibration data at all.
     They are excluded, not worked around.

  2. **Discard leading-edge vibration bursts occurring before temperature
     coverage begins**, as a general within-run edge-trimming rule (not a
     bearing-specific exception): any vibration burst whose timestamp
     falls before the first second temperature actually covers is dropped.
     Empirically verified to affect 11 bearings (`Bearing1_1, 1_2, 2_1,
     3_1` training; `Bearing1_4, 1_5, 1_6, 1_7, 2_4, 2_7, 3_3` test),
     dropping 75 bursts total (≈810 seconds combined, ≈13.5 minutes),
     fully resolving 10 of the 11 with zero residual anomalies. This rule
     applies generally to any bearing meeting this exact condition — it is
     not a one-off list.

  3. **For `Bearing1_1` ONLY, discard exactly two named files:**
     `acc_02121.csv` and `acc_02122.csv`, because their timestamps are
     demonstrably corrupted/non-monotonic (a backward jump from ~15:32:49
     to ~09:38:46 with no midnight-crossing pattern, sandwiched in an
     otherwise clean ~10s-cadence sequence). This is a hardcoded exclusion
     of these exact two files for this exact bearing — it does **NOT**
     establish, imply, or authorize any general corrupted-record-detection
     capability. Any future corrupted-record finding in any other bearing
     requires its own separate decision, not an extension of this one.

  `Bearing1_1` requires **both** treatment 2 and treatment 3 together to
  become loadable — treatment 3 alone leaves its 7 leading-edge bursts
  unresolved, and treatment 2 alone leaves its 2 corrupted-file anomaly
  unresolved.

  **These treatments are subtractive only.** No missing temperature is
  fabricated. No vibration timestamp is fabricated. No interpolation or
  backfilling of any kind is performed. No synthetic degradation signal is
  created. Each treatment only ever removes observations that cannot be
  legitimately represented under the already-approved D022 representation
  — it never repairs, estimates, or reconstructs a missing or corrupted
  observation. **"Discarding observations that cannot be legitimately
  represented" is the entire scope of this decision; "repairing or
  reconstructing missing or corrupted observations" is explicitly outside
  it and not authorized by any part of this entry.**

  No bearing changes train/test split membership as a result of any of
  these three treatments. The official 6-learning/11-test split is
  preserved in membership (no bearing moves from one split to the other);
  only the *usable* count within each split changes, from 6→4 training and
  11→8 test. After applying all three treatments, **12 of 17 bearings are
  expected to be loadable: 4 training (`Bearing1_1, 1_2, 2_1, 3_1`) + 8
  test (`Bearing1_4, 1_5, 1_6, 1_7, 2_4, 2_5, 2_7, 3_3`)** — `Bearing2_5`
  was already clean and loadable before this decision.

- **Reason:** Each treatment is individually evidenced against the full
  17-bearing audit (exact affected bearings/files, exact counts, empirical
  confirmation that the remaining data is fully contiguous/anomaly-free
  after treatment), is purely subtractive (never inventive), introduces no
  leakage/contamination risk (no bearing crosses the train/test boundary),
  and does not touch the representation, architecture, or semantics
  approved by D022. Bundling them mirrors this project's own precedent
  (D018, D021, D022 each bundled several related, evidenced sub-choices
  under one coherent theme) rather than fragmenting three tightly related,
  narrowly-scoped exclusion rules into separate entries.

- **Affects:** the not-yet-implemented PRONOSTIA-to-prognosis input-
  building code path (still does not exist — no loader, preprocessing,
  training, or test code is created or modified by this entry itself).

- **Does NOT resolve or authorize:** temperature interpolation; vibration
  interpolation; missing-temperature substitution (e.g. an alternative
  clock source for the 5 excluded bearings); treatment of the four
  uncovered channels (pressure, humidity, gas, current); HealthState
  thresholds/band definitions; failure_eta horizon or units; loss
  function; optimizer; training hyperparameters; training itself;
  PRONOSTIA train/evaluation methodology beyond the existing official
  6-learning/11-test split (e.g. any further re-splitting, cross-
  validation scheme, or leakage-prevention methodology); RL/U06; any
  pump-validation claim; or any general corrupted-record detection
  capability (treatment 3 is a two-file, one-bearing exclusion only, not a
  detection system).

- **Does NOT change:** D016, D017, D018, D019, D020, D021, D022 — all
  unchanged. No code, test, or dataset file is created or modified by this
  entry.

- **Status:** documentation-only; no implementation, remediation, code
  change, or training is performed or authorized by this entry.

### D024 — PRONOSTIA four-channel availability-indicator representation (pressure/humidity/gas/current)
- **Date:** 2026-08-31
- **Decision:** For the four channels PRONOSTIA does not and cannot
  provide (pressure, humidity, gas, current), this entry adopts Option B:
  a `0.0` placeholder value paired with one separate, explicit,
  per-timestep availability indicator per channel — four indicators
  total, one each for pressure, humidity, gas, and current. This directly
  extends D022's own `vibration_observed` mechanism (value zeroed,
  explicitly flagged as unobserved, rather than silently presented as
  real) to the four channels PRONOSTIA never supplies at all, for any
  timestep, in any PRONOSTIA-derived sequence.

  D024 establishes the eventual, fully-resulting prognosis input
  representation as **11 scalars per timestep**: the 6 original
  `CHANNELS` + 1 `vibration_observed` (D022, approved but not yet
  implemented in code) + 4 new per-channel availability indicators
  (pressure_observed, humidity_observed, gas_observed, current_observed).
  This is a specification decision about the eventual, resulting
  representation — it extends the previously-approved D022 representation
  (6 → 7) to 11. **It does not describe the current state of
  `edge/models/lstm_prognosis.py`, which remains committed and unchanged
  at input width 6** (D022's own `+1` widening has been decided but not
  yet implemented in code, and this entry does not implement it either).

  The `0.0` placeholder value for an unavailable channel is acceptable
  **only because** its paired availability indicator explicitly marks
  that value as unobserved at that timestep. The stored number by itself
  carries no claim of measurement; the indicator is what makes the
  representation honest. Without the indicator, a `0.0` placeholder would
  be indistinguishable from a genuine zero reading and would constitute
  exactly the kind of unflagged fabrication this project has repeatedly
  rejected (D017, D021, D022, D023).

  **`trust` MUST NOT be used to represent absence.** `trust=0` continues
  to mean, exclusively, low confidence in a genuine reading (FR-M3) —
  never "no measurement exists." This mirrors D022's own reasoning for
  why `vibration_observed` was introduced as a separate signal rather
  than overloading `trust`. For the four channels here, whatever `trust`
  value is technically supplied is mathematically inert given the `0.0`
  raw value (`0.0 × trust = 0.0` regardless) — but even so, `trust` is
  never the mechanism used to signal unavailability; the dedicated
  indicator is.

  The four availability indicators are **machine-readable absence
  markers only** — each is a structural signal that no measurement
  exists at that timestep for that channel. None of them is, or should
  ever be read as, evidence that pressure, humidity, gas, or current were
  measured, trained, validated, or physically mapped by PRONOSTIA in any
  respect. **This decision does not create, imply, or authorize any
  pump-validation claim of any kind.**

  **This entry authorizes the architecture/input-contract representation
  only. It does NOT authorize training, and no training may be described
  as validated or informed by this entry.**

- **Reason:** Reuses the one mechanism this project has already
  established and approved for exactly this situation (D022's
  `vibration_observed`) rather than inventing a new one, keeping the
  four-channel gap honestly represented without fabricating data or
  overloading `trust`'s existing FR-M3 meaning.

- **Affects:** the eventual, not-yet-implemented widening of
  `edge/models/lstm_prognosis.py`'s `_LSTMPrognosisNet.__init__`
  (`input_size` would eventually become 11) and its input-builder
  function — neither is implemented by this entry.

- **Does NOT resolve:** HealthState thresholds/band definitions;
  failure_eta horizon or units; loss function; optimizer; training
  hyperparameters; training methodology; any prognosis acceptance
  metric; RL/U06; any real pump/bench validation.

- **Does NOT change:** D021, D022, D023 — all unchanged. The currently
  committed `edge/models/lstm_prognosis.py` is not modified by this
  entry and remains at input width 6. No code, test, or dataset file is
  created or modified by this decision.

- **Status:** documentation-only; no implementation, training, or test
  code is created or authorized by this entry.

### D025 — PRONOSTIA prognosis-target methodology: training-bearing-only RUL, seconds unit, proportional HealthState bands (numeric thresholds deferred)
- **Date:** 2026-08-31
- **Decision:** Building on D021 (PRONOSTIA adopted for methodology-
  validation only) and D023 (12 of 17 bearings usable: 4 training, 8
  test), this entry establishes the target-generation methodology for
  FR-M1/M2 prognosis training, as follows:

  1. **RUL/failure_eta targets are generated ONLY for the 4 usable
     training-split bearings** (`Bearing1_1, 1_2, 2_1, 3_1`). Test-split
     bearings (`Bearing1_4, 1_5, 1_6, 1_7, 2_4, 2_5, 2_7, 3_3`) remain
     WITHOUT failure_eta training targets under this decision — D021's
     own text already identifies the test set as truncated, and no
     alternative endpoint source is authorized here. **This decision does
     NOT authorize use of `Validation_Set`/`Full_Test_Set` data in any
     form.** Test bearings must never be described or treated as having a
     known failure endpoint as a result of this decision.

  2. **Training-bearing RUL** is defined as:
     `RUL(t) = final_recorded_timestep_of_that_bearing − t`.
     The final recorded timestep of each training bearing's own sequence
     is assigned `RUL = 0`, grounded directly in D021's own approved
     "run to actual physical failure" language for the learning set — not
     a new empirical claim introduced by this entry.

  3. **`failure_eta` is represented in seconds.** Given the D022
     representation's confirmed gapless 1Hz structure, seconds and
     1Hz-timestep-index are numerically identical here; seconds is chosen
     as the more human-interpretable of the two, and the applicable half
     of `failure_eta`'s own existing wire-contract phrasing ("cycles/
     seconds ahead" — PRONOSTIA has no "cycles" concept).

  4. **HealthState will use bearing-relative/proportional RUL bands**,
     not fixed absolute-second bands — chosen specifically because the 4
     usable training bearings' lifetimes vary by roughly 17× (1,654s to
     27,952s per this project's own 17-bearing audit), which would make a
     single fixed-second threshold physically meaningless across bearings
     of such different scale. **The exact Warning/Critical proportions
     are explicitly NOT resolved by this entry** and require a separate,
     later, evidence-based decision (see the investigation this entry
     identifies but does not perform).

     Proportional bands, once numerically defined, are a **deliberately
     derived labeling methodology** — chosen because PRONOSTIA provides
     no Healthy/Warning/Critical annotation of any kind. They must never
     be described or treated as physically observed health-state labels;
     they are a modeling construct built on top of the RUL definition
     above.

  5. **Leakage discipline for target generation under this decision**:
     any per-bearing quantity (a bearing's own total lifetime, its own
     signal baseline) may be computed from that bearing's own history.
     Any cross-bearing or global statistic used in fitting RUL/HealthState
     target-generation parameters (e.g. shared proportion boundaries, if
     ever tuned rather than fixed a priori) must be derived using ONLY
     the 4 usable training bearings. Test-bearing data must never
     influence training-time threshold or statistic fitting.

- **Reason:** Directly grounded in D021's own already-approved language
  (run-to-failure learning set, truncated test set) and this project's
  own empirical findings (gapless 1Hz structure, 17× lifetime variation)
  — no external convention or paper-derived threshold is assumed. Avoids
  expanding PRONOSTIA dataset usage beyond D021/D023's current scope.

- **Affects:** the not-yet-written PRONOSTIA target-generation code (does
  not exist yet — no code, label, or training run is created by this
  entry itself) and any future training harness consuming it.

- **Does NOT resolve:** the exact numeric Warning/Critical proportions
  (requires a separate, later, evidence-based decision — see the
  investigation identified below, not performed by this entry); whether
  `Validation_Set`/`Full_Test_Set` is ever authorized as a test-bearing
  endpoint source (a fully separate, not-yet-proposed decision); training
  itself; windowing/stride/sampling methodology; loss function; optimizer;
  any training hyperparameter; acceptance metrics; RL/U06; any
  pump-validation claim.

- **Does NOT change:** D016–D024, all unchanged. D021's methodology-
  validation-only scope is unchanged and explicitly preserved — this
  entry does not add, reduce, or reinterpret that scope in any way. No
  code, test, label, or dataset file is created or modified by this
  entry.

- **Status:** documentation-only; no implementation, label generation, or
  training is performed or authorized by this entry.

### D026 — PRONOSTIA HealthState numeric proportions: 20% Warning / 5% Critical (explicit modeling policy, not empirically derived)
- **Date:** 2026-08-31
- **Decision:** Building on D025 (bearing-relative/proportional RUL bands
  adopted as the HealthState methodology, exact proportions left open),
  this entry resolves the two remaining numeric proportions as explicit,
  acknowledged modeling-policy values:

  - **Healthy:** `RUL > 20%` of that bearing's own total recorded
    lifetime.
  - **Warning:** `5% < RUL <= 20%`.
  - **Critical:** `RUL <= 5%`.

  **Both numbers are explicit modeling-policy choices, not empirically
  derived thresholds and not PRONOSTIA ground truth.** Neither claims the
  4 usable training bearings statistically determined these values.

  The **5% Critical** value is loosely informed by a qualitative,
  read-only investigation of the 4 D025 training bearings' own late-life
  vibration-RMS behavior, which found an approximate ~5–10% region of
  normalized life reasonably consistent with each bearing's own observed
  escalation. This is offered as **qualitative motivation only** — the
  investigation explicitly did not, and could not, statistically prove
  5% specifically over any other nearby value; the underlying analysis
  used only these 4 bearings, never test-split or `Validation_Set` data,
  never optimized against the observed outcomes, and drew no claim of
  generalization beyond this exploratory read.

  The **20% Warning** value has **no empirical threshold support** from
  the 4 training bearings — a dedicated investigation found the bearings'
  own degradation-onset timing is genuinely inconsistent (ranging from
  ~mid-life gradual onset to ~90%+ abrupt late onset across the four),
  such that no shared proportional Warning boundary is supported by the
  data at any value. 20% is adopted purely as a simple, round, transparent
  policy choice — explicitly not backed by, and not claimed to be
  supported by, the training-bearing evidence.

- **Reason:** A dedicated decision-readiness investigation (this
  session's own read-only work) concluded that continuing to search for
  an empirically-derived value was not justified: n=4 training bearings
  cannot responsibly support fitting or statistically validating a
  HealthState threshold, and the model's separate `failure_eta`
  regression head already carries the precise, continuous countdown —
  HealthState's legitimate role is a coarse, monotonic stage-of-life
  categorization complementing that precise value, not an independent
  precision instrument requiring empirical proof. Given that framing,
  simple, explicitly-labeled policy values (mirroring D020's
  `uncertainty_cap` precedent) are preferable to presenting either
  boundary as data-derived when the data does not support that claim.

- **Affects:** the not-yet-implemented PRONOSTIA HealthState
  target-generation code (does not exist yet — no label, code, or
  training run is created by this entry itself).

- **Does NOT resolve:** windowing/stride/sampling methodology; loss
  function; optimizer; any training hyperparameter; the target-generation
  implementation itself; training itself; acceptance metrics; RL/U06; any
  pump-validation claim; whether `Validation_Set`/`Full_Test_Set` is ever
  authorized (still not authorized by this or any entry).

- **Does NOT change:** D016–D025, all unchanged — in particular, D025's
  RUL/failure_eta methodology (training-bearings-only, seconds unit,
  final-timestep-anchor) is entirely untouched by this entry, which
  resolves the HealthState numeric proportions only. D025's leakage
  discipline (any cross-bearing/global statistic used in target
  generation must be fit using only the 4 usable training bearings; test-
  bearing data must never influence training-time threshold fitting) and
  its label-semantics requirement (HealthState labels are constructed
  modeling labels, not physical ground truth and not PRONOSTIA-provided
  annotations) both continue to apply in full, unmodified, to these two
  numbers. No code, test, label, or dataset file is created or modified
  by this entry.

- **Status:** documentation-only; no implementation, label generation, or
  training is performed or authorized by this entry.

### D027 — Physical hardware substitution: BMP280 replaces BMP180 (Pressure), Raspberry Pi 5 replaces Raspberry Pi 4 (edge node)
- **Date:** 2026-08-31
- **Decision:** The physical hardware inventory actually available differs
  from the parts named in `docs/SHTAPM_PRD-4.md` §12.1/BOM and
  `docs/SHTAPM_Doc02_TRD.md` in two places. Both are approved as physical
  substitutions, on the following explicit terms:

  1. **Pressure channel: BMP280 replaces the documented BMP180.** The
     logical telemetry channel remains `pressure` (`Channel.pressure` in
     the frozen contract, `backend/app/schemas/contracts.py` —
     unchanged). The measurement semantics remain exactly the
     atmospheric-pressure proxy already established by D010 and D014:
     BMP280 is, like BMP180, a barometric/absolute-pressure sensor — it
     reads ambient atmospheric pressure, **not** water-line/discharge
     pressure. **This substitution does not claim, and must never be
     described as providing, direct water-line/discharge pressure
     measurement.** BMP180 and BMP280 are NOT register-compatible (different
     chip-ID register value, different calibration-data layout, different
     compensation algorithm) — any future driver must be written for
     BMP280's own register map, not adapted from a BMP180 implementation.
     No BMP180-specific driver code exists anywhere in this repository to
     replace (`edge/drivers/` contains only the hardware-agnostic
     `SensorDriver`/`Reading` abstraction and test fakes — verified by
     direct inspection prior to this entry) — this substitution costs
     nothing in already-written code.

  2. **Edge node: Raspberry Pi 5 replaces the documented Raspberry Pi 4.**
     The existing SHTAPM architecture, module boundaries, and interfaces
     (`SensorDriver`/`Sensor` abstraction, GPIO/I²C/SPI/1-Wire channel
     assignments per §12.1/TRD §"Interfaces", MQTT/contract layer, safety
     loop running entirely at the edge) are all preserved unchanged. Pi 5
     is electrically pin-compatible with Pi 4 at the 40-pin GPIO header
     (same pinout, same 3.3V logic levels) for all six sensors, the
     MCP3008 ADC, INA219, and the relay. The one concrete software
     consideration this substitution introduces: Pi 5 uses a new GPIO
     controller (RP1) that the classic `RPi.GPIO` library does not
     support — any future driver/acquisition code using `gpiozero` (as
     already named in TRD's sensor-libs table) must select a Pi-5-
     compatible pin factory (e.g. `lgpio`) rather than relying on the
     default. I2C (`smbus2`), SPI (`spidev`), and 1-Wire
     (`w1thermsensor`) are expected to continue working via the standard
     Linux kernel interfaces on Pi 5, but this has not been physically
     verified in this repository as of this entry.

  3. **The six-channel design is entirely unchanged by this entry**: same
     six logical channels, same order, same names
     (temperature/vibration/pressure/humidity/gas/current), same
     remaining four physical parts (DS18B20, ADXL335, DHT22, MQ-135), same
     MCP3008/INA219 supporting hardware. No channel is added, removed,
     reordered, or renamed. No new sensor or channel is introduced.

- **Reason:** The physical hardware actually in hand does not match two
  named BOM items in the original planning documents. Per this project's
  own established precedent for hardware substitution (the PRD itself
  documents the ACS712→INA219 substitution explicitly, by name, with
  stated rationale — PRD §12.1 note, Risk R5), and per `CLAUDE.md`'s rule
  against silently changing approved architecture, this substitution is
  recorded explicitly rather than absorbed silently into future driver
  code. Both substitutions were analyzed (this session, read-only) before
  this entry: neither changes the logical channel contract, the six-
  channel design, or D010/D014's documented pressure-proxy reasoning —
  which applies equally to BMP280 as it did to BMP180, since both are the
  same class of absolute-pressure sensor.

- **Affects:** any future physical driver implementation for the pressure
  channel (must target BMP280's own register map) and any future
  acquisition-runtime GPIO backend selection (must target a Pi-5-
  compatible `gpiozero` pin factory). Does not affect the frozen wire
  contract, the `SensorDriver`/`Sensor` abstraction, or any already-
  committed code — no driver code for either BMP180 or Pi-4-specific GPIO
  access exists anywhere in this repository to modify.

- **Does NOT resolve:** actual driver implementation for BMP280 (register
  reads, compensation formula) — not implemented by this entry; physical
  verification of I2C/SPI/1-Wire behavior on Pi 5 — not performed by this
  entry, still required before physical acquisition is considered
  complete; the BMP280 breakout board's specific supply-voltage tolerance
  — board-dependent, not verified here; any P0/P1 hardware-blocked
  acceptance item (physical sensor reads, INA219 current resolution,
  on-Pi `<500ms` LSTM+IF timing, physical relay safe-stop) — all remain
  exactly as blocked as before this entry, now simply blocked on BMP280/
  Pi 5 instead of BMP180/Pi 4.

- **Does NOT change:** D001–D026, all unchanged. **D010 and D014's
  historical text is preserved exactly as originally recorded** — both
  entries continue to document the reasoning that was actually used at
  the time (BMP180 named specifically, because that was the part
  documented then); this entry does not retroactively edit either to
  make BMP280 appear as though it were the original choice. D010/D014's
  underlying atmospheric-pressure-proxy *finding* is reaffirmed as
  applying equally to BMP280 (see Decision pt. 1), but their text itself
  is untouched. `docs/SHTAPM_PRD-4.md` and `docs/SHTAPM_Doc02_TRD.md` are
  not modified by this entry — they continue to name BMP180/Raspberry Pi
  4 as originally written; this entry is the authoritative record of the
  physical substitution actually in use, layered on top of, not
  overwriting, the original documentation.

- **Status:** documentation-only; no driver code, acquisition-runtime
  change, or hardware wiring/connection is performed or authorized by
  this entry.

---

## UNDECIDED (must not be silently resolved — see CURRENT_STATE blockers)
- U01 — Beta-reputation trust-update formula + recovery dynamics (P2). **Partial:** `h` resolved
  (D009). **Still open:** lambda=0.7 forgetting factor (PENDING approval); `c` consistency signal
  definition (UNDECIDED).
- U02 — Fault-vs-attack physics/correlation attribution rules + thresholds (P2). **Partial:**
  channel pair (current↔vibration) + heuristic approach resolved (D010), implemented in
  `k_correlation.py`; a minimal provisional `PhysicsRule` reusing that same heuristic now
  exists and is wired into `AttributionEngine` (D013), unblocking `attribution=attack` for
  that pair only. **Still open:** real physics validation (does the correlation hold on
  real data; what tolerance beyond sign comparison) — requires bench data or a dataset (U07);
  no rule exists for the other four channels; even for current/vibration, D013's own
  multi-seed testing found only ~50–60% attribution reliability — not a validated capability.
- U05 — `divergence_threshold` value (P3). **Partial:**
  behavioral design resolved by D018 (divergence computation form, recovery rule,
  60s-expiry escalation, uncertainty interface, cycle sequencing); uncertainty-
  estimation method resolved provisionally by D019 (deterministic
  elapsed-substitution-time proxy, single-signal, no reconstruction-stability
  or divergence input); uncertainty-cap value (0.8) and the time→uncertainty
  scaling formula (linear, `f(x)=x`, output domain [0,1]) resolved by D020
  (policy decision, not data-gated). **Still open:** `divergence_threshold`'s
  numeric value only — data-gated, needs real reconstruction-error and
  fault/attack-separation statistics.
- U06 — RL reward shaping + acceptable false-isolation rate (P3). **Status: fully
  open, zero partial resolution.** A specification PROPOSAL (not a decision, not
  a partial resolution) exists below — see "U06 — RL REWARD SHAPING
  SPECIFICATION PROPOSAL" at the end of this file.
- U07 — SWaT/WADI dataset access vs TEP+bench substitute (P2/P7). **Partial:**
  validation methodology frozen (D011); SWaT.A1 access obtained and the
  six-tag mapping selected (D012). **Still open:** building/running the
  evaluation harness itself.
- U08 — Backend host for demo: on-Pi vs laptop (P0/P6).
- U09 — Pump model + rated current (sizes INA219 shunt/relay) (P1 hardware).
- U10 — Demo role/user count; MQTT credential/TLS scope for localhost demo (P4).
- U11 — Dashboard branding (logo/palette) beyond Aurora defaults (P5).
- U12 — Primary graded artifact: live demo vs paper (shifts P6/P7 weighting).
- U13 — White-box adaptive-adversary evaluation in submission scope or future (P7).
- U14 — `…/command` (scenario-inject) message payload is UNSPECIFIED in all docs (TRD §02.3 names the topic only). Blocks P4 injection (FR-A4/FR-D7). Not part of the M2 telemetry/decision/ledger freeze; do not invent.

---

## U06 — RL REWARD SHAPING SPECIFICATION PROPOSAL
**(PROPOSAL ONLY — NOT A DECISION. U06 REMAINS FULLY UNDECIDED/OPEN. Nothing in
this section resolves, partially resolves, or authorizes implementation of any
item it discusses. No numeric threshold named below is approved, final, or
production-usable. This section exists to define terms and evidence
requirements precisely enough that a future, separate decision entry could
resolve U06 — it is not that entry.)**

- **Date drafted:** 2026-09-06
- **Author's own status for this section:** documentation-only planning,
  produced by a read-only architecture review (`edge/rl/reward.py`,
  `edge/rl/environment.py`, `edge/rl/fallback_gate.py`, `edge/rl/policy.py`,
  `edge/eval/rl_training.py`, `edge/eval/rl_baseline_eval.py`, and their
  tests, as committed at `1702b666f19540b8a51ffb932661fa56c64cf5dd`). No
  code, test, fixture, or configuration file is created, modified, or
  implied to change by this section.

### 1. Proposed definitions (terms only — not thresholds)

- **False isolation (proposed definition):** a step where the deterministic
  ground-truth safety condition (`edge.rl.fallback_gate.GateDecision.
  safety_status == "nominal"`) holds, but the action *requested* to the gate
  was `RLAction.isolate` or `RLAction.reduce_weight`. This mirrors exactly
  the condition `edge/rl/reward.py`'s `isolation_appropriateness` component
  already scores as `-PENALTY_MAGNITUDE_FIXTURE` — the proposal is to name
  and count this condition as a rate, not to change how it is scored.
- **Missed critical fault (proposed definition):** a step where
  `safety_status == "isolation_active"` (the deterministic tracker already
  holds a channel as a candidate) but the action *requested* was
  `RLAction.continue_`. Again, this is the existing second branch of
  `isolation_appropriateness`, proposed to be named and counted separately
  from false isolation rather than left merged into one signed component
  value.
- Both definitions are evaluated against `requested_action`, matching the
  reward module's own existing anti-gate-exploitation choice (see
  `edge/rl/reward.py`'s "REUSE, NOT RE-DERIVATION" section) — using
  `approved_action` instead would hide a policy's true intent behind the
  gate's own corrections and understate both rates.

### 2. Proposed denominator and unit for each rate

- **False-isolation rate (proposed):** (count of false-isolation steps, as
  defined above) ÷ (count of steps where `safety_status == "nominal"` AND a
  request was made) — i.e., false isolations as a fraction of nominal-state
  opportunities to (wrongly) isolate, not a fraction of all steps. A per-
  all-steps denominator would understate the rate on scenarios dominated by
  non-nominal conditions.
- **Missed-critical-fault rate (proposed):** (count of missed-fault steps)
  ÷ (count of steps where `safety_status == "isolation_active"`) — misses
  as a fraction of actual fault-opportunity steps, for the same reason.
- **Unit:** a dimensionless proportion in `[0, 1]` per evaluation episode,
  additionally proposed to be reported per-scenario (never pooled silently
  across scenarios of different generator/injection configurations, which
  would conflate distinct fault mixes into one number).
- Neither denominator can be zero-guarded away silently: a scenario with
  zero nominal steps, or zero isolation-active steps, would need its rate
  reported as `None`/undefined for that scenario, not as `0.0` (which would
  misrepresent "no opportunity to fail" as "never failed").

### 3. Proposed scenario coverage requirements

- At minimum, coverage proportional to what already exists structurally:
  every held-out `EVALUATION_SCENARIOS` entry (`SCENARIO_CLEAN_DEGRADATION`,
  `SCENARIO_INJECTED_CURRENT_SPIKE`) plus at least one scenario per
  currently-implemented injection type in `edge/injection/injections.py`
  that has not yet been exercised in any RL evaluation scenario — an
  incomplete injection-type census would leave false-isolation/missed-fault
  rates measured on an arbitrary, unstated subset of fault types.
- Any new scenario added for this purpose must remain in a held-out set,
  never added to `TRAINING_SCENARIOS`, preserving the leakage discipline
  `edge/eval/rl_training.py` already documents.
- Coverage claims must state which injection types were and were not
  exercised — proposed as an explicit table in whatever evidence report is
  eventually produced, not a single pooled number.

### 4. Proposed seed/repetition requirements

- Proposed minimum: each scenario evaluated across a fixed, documented set
  of at least 5 distinct seeds (distinct from any seed already used in
  `TRAINING_SCENARIOS`/`EVALUATION_SCENARIOS`, to avoid conflating training
  determinism with evaluation robustness), following the same "one shared
  `random.Random(seed)` + `torch.manual_seed(seed)`" determinism convention
  `edge/eval/rl_training.py` already uses.
- Proposed rationale for 5 (illustrative, not derived from any statistical
  power calculation): enough to observe whether a rate is stable or highly
  seed-sensitive, without implying a specific confidence level — an actual
  power/sample-size calculation is listed as still-needed evidence in
  §5/§8 below, not supplied here.

### 5. Proposed confidence-interval / uncertainty reporting

- Proposed: report each rate as a point estimate plus a Wilson or
  Clopper-Pearson binomial confidence interval (appropriate for a
  proportion-of-successes measurement with a small step/episode count),
  computed per scenario, never a bare point estimate presented alone.
- Proposed: explicitly report the denominator size (number of
  opportunity-steps) alongside every rate — a rate computed from a small
  denominator (e.g., a short episode with few `isolation_active` steps)
  must not be presented with the same apparent precision as one from a
  large denominator.
- None of the above interval methodology is implemented, chosen as final,
  or applied to any existing number in this repo by this proposal.

### 6. Whether synthetic data is diagnostic only (proposed answer: yes)

- Proposed position: every rate computed under the current synthetic
  generator/injection framework is **diagnostic only** — informative about
  this codebase's own internal consistency (does the reward/gate/tracker
  pipeline behave as designed on manufactured trajectories), and NOT
  evidence of real-world false-isolation or fault-detection performance.
  This mirrors the same diagnostic-only stance already established for P2
  SWaT work (`CURRENT_STATE.md`'s "P2 SWaT DIAGNOSTICS: DIAGNOSTICALLY
  COMPLETE (probes, not acceptance)") and for prognosis
  (`edge/eval/pronostia_prognosis_training.py`'s proxy-validation framing) —
  applying the same discipline here, not inventing a new one.

### 7. Proposed real hardware/bench evidence requirements

Proposed as necessary (not sufficient — see §8) before any false-isolation
or missed-fault rate could be treated as more than diagnostic:
- Real telemetry from the actual pump/bench rig covering both nominal
  operation and at least one real fault condition per channel category
  the project claims to detect (mirroring D021/D022's own "same-failure-
  mode-class proxy, real pump/bench validation still required" stance for
  prognosis — U06 should not be held to a lower evidentiary bar than
  prognosis already is).
- A real (or at minimum, real-telemetry-replayed) run through the
  unmodified `SHTAPMSimulationEnvironment`/fallback-gate/reward pipeline,
  not a re-implementation — to isolate "does the existing pipeline's
  behavior generalize" from "does a new pipeline behave differently."
- Resolution of the environment's own documented "world-inert" limitation
  (see §9) for at least `reduce_weight`, since a real false-isolation-rate
  claim that never exercises a real down-weighting effect cannot speak to
  whether down-weighting is an appropriate response at all.

### 8. Proposed evidence required before selecting any reward weights

Proposed, cumulative (each item is necessary, none alone is sufficient):
1. A committed, repeatable (not one-off/informal) simulation diagnostic
   comparing all four existing named fixtures
   (`SIMULATION_REWARD_WEIGHTS_FIXTURE`, `SAFETY_PRIORITY_WEIGHTS_FIXTURE`,
   `DECISION_ONLY_WEIGHTS_FIXTURE`, `BALANCED_SURVIVAL_WEIGHTS_FIXTURE`)
   across the scenario/seed coverage in §3/§4, reporting rates per §2 with
   uncertainty per §5 — turning the current one-off "~150x" observation
   into reproducible, committed evidence.
2. An explicit statement of what the false-isolation/missed-fault rate
   *should* be traded off against (e.g., downtime cost, sensor-recovery
   cost) — no such tradeoff has been specified anywhere in `docs/` or
   `DECISIONS.md`; without it, "acceptable rate" has no objective function
   to be acceptable *with respect to*.
3. Real bench/hardware evidence per §7, at least at the "does the direction
   of the effect hold outside synthetic data" level — full production
   validation is a separate, later bar.
4. A named, dated decision-log entry (a future D0xx, not this section)
   that a specific rate/tradeoff and a specific weight configuration were
   chosen, with #1-#3 cited as its basis.
- Absent all four, selecting any weight configuration as "the" answer would
  be exactly the "silently resolving U06" outcome `DECISIONS.md`'s own
  header (line 5) forbids.

### 9. World-inert limitation: present results are not fault-detection evidence

Restating and binding forward, for U06 specifically, what
`edge/eval/rl_training.py`'s own module docstring already documents: the
current `SHTAPMSimulationEnvironment` action-dependent transition model
gives `continue_`, `alert`, and `reduce_weight` **no trajectory effect
whatsoever** — only `isolate` (held-last-value substitution) and
`safe_stop` (episode termination) change what happens next. A direct
consequence, proposed here as an explicit constraint on any U06 evidence
claim: **no false-isolation or missed-critical-fault rate measured under
the current environment can be interpreted as evidence about real
fault-detection or false-isolation behavior** — it can only measure
whether the reward/gate/tracker bookkeeping is internally consistent on a
world that does not react to three of five possible actions. Any future
evidence report under this proposal must carry this caveat verbatim or
equivalent, not as a footnote but as a scope-defining statement alongside
any reported rate.

### 10. Distinguishing five related levers (proposed terminology, for future
entries to reference precisely rather than conflating them)

- **Reward-weight tuning:** choosing a `RewardWeights` instance to combine
  the seven already-computed, unchanged `RewardComponents` into `total`
  (exactly what `SIMULATION_REWARD_WEIGHTS_FIXTURE` and its three sibling
  fixtures already do). Does not touch component definitions, the
  environment, the gate, or episode length.
- **Reward normalization:** rescaling or bounding components/`total` (e.g.,
  per-step averaging, min-max, z-scoring) so magnitudes are comparable
  across episodes/configurations. Not implemented anywhere in this repo;
  would change `RewardResult`'s numeric meaning, not merely its weighting.
- **Discount-factor (γ) selection:** the existing `train_dqn(gamma=...)`
  hyperparameter controlling how much a Bellman update values future
  reward during training. Orthogonal to reward-weight tuning — it affects
  what the DQN target network learns to value, never what
  `compute_reward()` returns for a given step.
- **Episode-length-normalized reporting:** computing a derived, additive
  reporting metric (e.g., mean reward per step) alongside existing
  `cumulative_reward`, without changing `cumulative_reward` itself or what
  the policy is trained against. Purely an aggregation/reporting-layer
  concern.
- **Real-world validation:** confirming any of the above against actual
  hardware/bench telemetry (see §7) — categorically separate from, and not
  substitutable by, any amount of further simulation-only work under §6/§9.

### 11. Explicitly not done by this proposal

- No reward weight is selected, recommended, ranked, or implied to be
  closer to final than any other.
- No numeric false-isolation or missed-critical-fault rate is presented as
  an approved, acceptable, or target threshold — every number named above
  (5 seeds, a specific interval method) is proposed methodology, not a
  result or a threshold.
- No code, test, fixture, environment behavior, training logic, or
  configuration is created or modified by this entry.
- U06's status in the UNDECIDED list above is unchanged: fully open, zero
  partial resolution.

---

## U06 — Operational Definitions Proposal: False Isolation and Missed Critical Faults
**(PROPOSAL ONLY — NOT A DECISION. U06 REMAINS FULLY UNDECIDED/OPEN. This is a
follow-up scoping subsection to the "U06 — RL REWARD SHAPING SPECIFICATION
PROPOSAL" section above, narrowed to the smallest concrete U06 decision item:
operational definitions and measurement units for "false isolation" and
"missed critical fault." Nothing in this subsection resolves, partially
resolves, or authorizes implementation of any item it discusses. No numeric
threshold named below is approved, final, or production-usable.)**

- **Date drafted:** 2026-09-06
- **Author's own status for this subsection:** documentation-only planning,
  produced by a read-only review of `edge/rl/reward.py`,
  `edge/rl/environment.py`, `edge/rl/fallback_gate.py`,
  `edge/eval/rl_baseline_eval.py`, `edge/eval/rl_training.py`,
  `edge/injection/injections.py`, and their tests, as committed at
  `6e42c0d86804f78ce00855835eda6d481bbe665a`. No code, test, fixture, or
  configuration file is created, modified, or implied to change by this
  subsection.

### A. Proposed definition — false isolation

A step is proposed to count as a **false isolation** iff:
- `gate_decision.safety_status == "nominal"`, **and**
- `gate_decision.requested_action ∈ {RLAction.isolate, RLAction.reduce_weight}`.

Counted by **requested action**, never `approved_action` — matching
`edge/rl/reward.py`'s own existing anti-gate-exploitation choice (scoring the
gate-approved outcome instead would hide a policy's true intent behind the
gate's own correction and understate the rate). This is exactly the first
branch of `_compute_components()`'s `isolation_appropriateness`
(`edge/rl/reward.py`) — the proposal only names and counts it as a rate, it
does not change how it is scored.

### B. Proposed definition — missed critical fault

A step is proposed to count as a **missed critical fault** iff:
- `gate_decision.safety_status == "isolation_active"`, **and**
- `gate_decision.requested_action is RLAction.continue_`.

**`safety_status` is explicitly labeled a proxy, not independent fault
ground truth**: it reflects `IsolationFallbackTracker`'s own derived
response to whatever the anomaly/attribution pipeline already flagged, not
an independent, injection-level record of whether a fault was actually
present in that frame. No code anywhere currently cross-references
`safety_status` against `edge.injection.injections.Injection`'s own onset/
duration/amplitude parameters — this is a known gap, not a solved problem
(see §D below).

### C. Proposed opportunity denominators

| Rate | Numerator | Denominator |
|---|---|---|
| False-isolation rate | steps meeting §A | `safety_status == "nominal"` steps with `requested_action is not None` |
| Missed-critical-fault rate | steps meeting §B | `safety_status == "isolation_active"` steps |

Both denominators are opportunity counts, never total step counts. **A
zero-denominator scenario/episode (no nominal steps, or no isolation-active
steps) must report the rate as undefined/`None` for that scenario — never
as `0%`**, which would misrepresent "no opportunity to fail" as "never
failed."

### D. Distinguishing four layers already present in the code

- **Requested action** (`gate_decision.requested_action`) — what the
  policy/baseline wanted; §A/§B are evaluated here.
- **Gate-approved action** (`gate_decision.approved_action`) — what the
  fallback gate actually let through; termination and the simulation
  transition key off this, never off the request.
- **Executed simulation transition** — what `edge/rl/environment.py`'s
  `step()` actually did: held-last-value substitution (only if
  `approved_action is RLAction.isolate`), skip-entirely (only if
  `approved_action is RLAction.safe_stop`), or no trajectory effect at all
  (`continue_`/`alert`/`reduce_weight`, regardless of what was requested or
  approved).
- **Scenario/injection ground truth** — the synthetic generator's `health`
  array plus whatever `edge.injection.injections.Injection` was configured.
  This is the only layer that could, in principle, independently confirm
  whether a fault was actually present at a given frame, and it is not
  currently compared against `safety_status` anywhere (see §B's proxy
  caveat).

### E. Reporting granularity: per scenario, per episode, then cross-seed

- Rates are proposed to be computed **per scenario** (never pooled across
  scenarios — `clean_degradation` and `injected_current_spike` are
  structurally different fault mixes; pooling would conflate them with no
  way to attribute a rate change to either).
- Within a scenario, **per-episode raw rates and opportunity counts are the
  base unit**, reported before any cross-seed summary — a single episode's
  opportunity count can be small enough (e.g., a 40-step scenario) that a
  bare summary statistic would hide instability.
- Scenario identity (`scenario_name`) must be preserved at every stage of
  aggregation, never collapsed into an unlabeled combined number.

### F. Cases requiring separate reporting (not silently folded into the rate)

- **`safe_stop` requests** — never scored as a false isolation or missed
  fault by §A/§B (the conditions cannot co-occur with
  `requested_action is RLAction.safe_stop`), but must be reported as their
  own row (count/rate of `safe_stop` requests) — a policy that always
  safe-stops would trivially show 0% false isolation while being useless.
- **Policy fallback / unvalidated status**
  (`policy_status ∈ {"unavailable", "unvalidated", "validated_low_confidence"}`)
  — §A/§B still evaluate the *requester's* intent on these steps, but a
  `policy_status` breakdown must be reported alongside every rate, since a
  policy that is almost always fallback-overridden (e.g. `BaselinePolicy`,
  which is always `policy_validated=False`) would otherwise look
  misleadingly clean.
- **World-inert approved actions** (`continue_`, `alert`, `reduce_weight`
  when *approved*) — these produce no trajectory effect; report the count
  of opportunity-steps with a world-inert approved action separately so a
  reader can see how much of the denominator carries no environmental
  feedback.
- **Clean degradation** vs. **injected current spike** scenarios — always
  reported as fully separate rows, never merged (per §E).
- **Early safe-stop termination** (`termination_cause == "safe_stop"` on
  `EpisodeRecord`) — report `step_count` and `termination_cause` alongside
  every rate; an episode terminated early contributes a smaller opportunity
  count than one that runs to exhaustion, and pooling without this context
  would bias the rate toward whichever termination pattern yields more
  opportunity-steps.

### G. What current code can and cannot measure

**Can measure reliably today**, using already-existing, deterministic,
reproducible fields (`TransitionRecord`/`GateDecision`/`RewardComponents`
in `edge/eval/rl_baseline_eval.py`/`edge/eval/rl_training.py`): every
quantity in §A–§F, exactly as defined, for the two existing scenarios.

**Cannot measure, because of the world-inert simulation limitation**:
- Whether a false isolation or missed fault actually cost anything in
  simulation — since `continue_`/`alert`/`reduce_weight` have no trajectory
  effect, a "missed" fault looks identical going forward to a correct
  `continue_`, except for that one step's reward penalty; there is no
  compounding consequence to observe.
- Whether `safety_status == "isolation_active"` (§B's proxy) actually
  corresponds to a real fault frame from the injection's own ground truth —
  no cross-reference against injection onset/duration exists yet.
- **Anything about real sensors, real faults, or real attacks. The current
  world-inert simulation cannot establish real fault-detection consequences
  or real-world false-isolation/missed-fault rates** — every number
  obtainable today is a property of this codebase's own internal
  consistency on manufactured trajectories, restated here for this specific
  definitions item, consistent with the "U06 — RL REWARD SHAPING
  SPECIFICATION PROPOSAL" section's own §6/§9 above.

### H. Proposed minimum scenario taxonomy before any rate is calculated

Currently exactly two named RL scenarios exist
(`SCENARIO_CLEAN_DEGRADATION`, `SCENARIO_INJECTED_CURRENT_SPIKE`),
exercising one of eight implemented injection types (`Spike`; the other
seven — `Drift`, `StuckAt`, `BiasFDI`, `RampFDI`, `Replay`, `ConstantSpoof`,
`AdaptiveStealthFDI`, all in `edge/injection/injections.py` — are never used
in any RL-pathway scenario). Proposed minimum before any rate is treated as
more than a two-scenario spot-check:
1. One scenario per injection type (all eight), each held out from training
   exactly as the current two are.
2. At least one zero-fault (clean) scenario per distinct degradation
   profile already used in training vs. evaluation, to measure the
   false-isolation side without an injected fault confounding it.
3. Explicit, per-scenario labeling of which channel(s) and which injection
   parameters (onset, duration, amplitude) constitute "a fault is present,"
   so a future ground-truth cross-reference (§D/§G) has something concrete
   to compare against.
4. A documented statement of which fault types remain untested even after
   (1)–(3) (e.g., multi-channel simultaneous faults) — coverage gaps must
   be stated, not left implicit.

### I. Proposed evidence needed before accepting these definitions

Before any future `DECISIONS.md` entry marks these *definitions themselves*
as decided (not any rate — the definitions):
1. A worked example, run once and included in the review, of §A/§B's
   counts on the existing, already-committed `EpisodeRecord`/
   `TransitionRecord` output for both existing scenarios — confirming the
   definitions produce sensible, non-degenerate counts on real,
   already-existing data.
2. Explicit sign-off on whether `safety_status` is an acceptable proxy for
   "a fault is present" (§B's known gap), or a decision to build the
   ground-truth cross-reference first if it is not acceptable.
3. Agreement that the opportunity-denominator convention (§C) and the
   per-scenario/per-episode-then-cross-seed reporting convention (§E) match
   how a future evidence report (per the "U06 — RL REWARD SHAPING
   SPECIFICATION PROPOSAL" section's §8 above) intends to consume these
   numbers.
4. **No numeric threshold is required at this stage** — this evidence list
   is only for accepting the *definitions and measurement units*, not any
   acceptable rate.

### J. Explicitly not done by this subsection

- No metric, code, test, experiment, reward change, normalization, or
  training change is implemented.
- No acceptable numerical false-isolation or missed-critical-fault
  threshold is chosen.
- No current or hypothetical simulation result is claimed to be
  real-world, validated, safe, accurate, optimal, or production-ready.
- U06's status in the UNDECIDED list above is unchanged: fully open, zero
  partial resolution. This subsection is a proposal for one future decision
  item, not that decision.

---

## U06 — Scenario-Taxonomy Implementation Note (IMPLEMENTATION RECORD, NOT A DECISION)
**(U06 REMAINS FULLY UNDECIDED/OPEN. This is an implementation record for
the smallest approved scenario-taxonomy increment scoped in the two U06
proposal sections above — it documents what was added, not a resolution of
false-isolation/missed-fault definitions, rates, or reward weights.)**

- **Date implemented:** 2026-09-06
- **Files changed:** `edge/eval/rl_baseline_eval.py`, `edge/eval/rl_training.py`,
  `edge/tests/test_rl_baseline_eval.py`, `edge/tests/test_rl_training.py`. No
  reward, environment, fallback-gate, policy, or DQN file changed.

**Scenario inventory (final, this increment):**

| Scenario | Seed | Channel | Injection type | Onset | Duration | Parameters | Active window |
|---|---|---|---|---|---|---|---|
| `clean_degradation` (unchanged) | 1337 | — | none | — | — | — | — |
| `injected_current_spike` (unchanged) | 1338 | current | Spike | 32 | 5 | amplitude=50.0 | [32, 37) |
| `injected_temperature_drift` | 1339 | temperature | Drift | 30 | 5 | rate=0.5 | [30, 35) |
| `injected_pressure_stuck_at` | 1340 | pressure | StuckAt | 30 | 5 | (default held_value) | [30, 35) |
| `injected_humidity_bias_fdi` | 1341 | humidity | BiasFDI | 30 | 5 | bias=5.0 | [30, 35) |
| `injected_gas_ramp_fdi` | 1342 | gas | RampFDI | 28 | 8 | slope=0.8 | [28, 36) |
| `injected_vibration_replay` | 1343 | vibration | Replay | 30 | 5 | source_onset=0 | [30, 35) |
| `injected_current_constant_spoof` | 1344 | current | ConstantSpoof | 30 | 5 | value=0.0 | [30, 35) |
| `injected_temperature_adaptive_stealth_fdi` | 1345 | temperature | AdaptiveStealthFDI | 25 | 10 | rate=0.5, residual_cap=2.0 | [25, 35) |

All nine scenarios share the same reused degradation profile (`start_health=1.0`, `end_health=0.2`, `degradation_rate=1.0`, `vibration` 0.03→1.2, `length=40`) except `injected_current_spike`/`clean_degradation`'s own pre-existing identical shape — unchanged from before this increment. All nine are in `EVALUATION_SCENARIOS`; `TRAINING_SCENARIOS` (`training_a` seed 2001, `training_b` seed 2002) is untouched. No tuning scenario set was introduced.

An additive, descriptive-only `ScenarioMetadata`/`EVALUATION_SCENARIO_METADATA` structure was added in `edge/eval/rl_baseline_eval.py`, recording each scenario's purpose, clean/fault/attack classification, injection type, channel, onset/duration/parameters, expected active window, scenario set, and known limitations — this changes no existing `ScenarioConfig` field, constructor, or function signature, and is not consumed by any training/evaluation/reward code path.

**Intentional, documented gaps (not addressed by this increment):**
- Every scenario injects at most one channel with at most one fault/attack — no simultaneous multi-channel or multi-fault scenario exists.
- No scenario besides `clean_degradation` covers a degradation profile other than the one shared shape reused throughout this taxonomy.
- `InjectionResult.labels` (the per-frame ground truth `Injection.apply()` already computes) is still discarded by `SHTAPMSimulationEnvironment.__init__` — not threaded through by this increment, per this increment's own approved scope.
- No ground-truth comparison, rate calculation, reward-weight selection, normalization, gate change, policy change, or DQN change was made.

**Not done by this increment:** no false-isolation or missed-critical-fault rate is computed or claimed; no numeric threshold is chosen; no claim of real-world, validated, safe, accurate, optimal, or production-ready behavior is made for any scenario. U06's status in the UNDECIDED list above is unchanged: fully open, zero partial resolution.

---

## U06 — Injection-Label Retention Implementation Note (IMPLEMENTATION RECORD, NOT A DECISION)
**(U06 REMAINS FULLY UNDECIDED/OPEN. This is an implementation record for the smallest approved label-retention increment scoped in the "U06 scenario-taxonomy implementation plan" review above — it documents what was added, not a resolution of false-isolation/missed-fault definitions, rates, comparisons, or reward weights.)**

- **Date implemented:** 2026-09-06
- **Files changed:** `edge/rl/environment.py`, `edge/eval/rl_baseline_eval.py`, `edge/tests/test_rl_environment.py`, `edge/tests/test_rl_baseline_eval.py`. No reward, fallback-gate, policy, DQN, or hardware/actuation file changed.

**What this increment does:**
- `SHTAPMSimulationEnvironment.__init__` now retains each injection's `InjectionResult.labels` (previously discarded every loop iteration) into `self._labels_by_sample_seq: dict[int, tuple[Label, ...]]`, keyed by `sample_seq`, containing only `active=True` entries, with multiple simultaneous injections on different channels both retained (never overwritten) as separate tuple entries at the same key.
- `step()` now exposes the current frame's `sample_seq` in `EnvironmentStepResult.info["sample_seq"]`, sourced from the same `self._latest_raw.sample_seq` identity `_build_state()` already uses.
- `edge/eval/rl_baseline_eval.py`'s `TransitionRecord` gains one new, defaulted field, `active_injection_labels: tuple[str, ...] = ()` — raw `injection_type` name strings (e.g. `("spike",)`) active at that step's `sample_seq`, populated in `_run_episode` by joining `result.info["sample_seq"]` against the environment's retained labels.

**What this increment explicitly does NOT do:**
- No comparison between `Label.active`/`Label.channel`/`Label.injection_type` and `safety_status`, `requested_action`, `approved_action`, `fallback_used`, `policy_status`, or `reward_components.isolation_appropriateness` is implemented.
- No false-isolation rate, missed-critical-fault rate, threshold, or verdict is computed, stored, or claimed anywhere.
- No reward, fallback-gate, policy, transition, or DQN logic changed — `self._frames` generation is byte-identical to before this increment; only the previously-discarded `.labels` output of the same, already-existing `injection.apply()` calls is now also captured.
- No claim of real-world fault detection, real false-isolation rate, acceptable threshold, policy effectiveness, safety, or production readiness is made.

**Not done by this increment:** U06's status in the UNDECIDED list above is unchanged: fully open, zero partial resolution. This is a data-plumbing increment only, preparing the inputs a future, separate, not-yet-approved comparison increment would need.

---

## U06 — Axis (i) Proxy-Based Rate Summary Implementation Note (IMPLEMENTATION RECORD, NOT A DECISION)
**(U06 REMAINS FULLY UNDECIDED/OPEN. This is an implementation record for the narrowest approved comparison increment scoped in the "U06 comparison implementation" review above — it implements the already-proposed, proxy-based axis (i) rate definitions as an additive simulation-only summary. It does not resolve U06, choose a threshold, or implement axes (ii)/(iii).)**

- **Date implemented:** 2026-09-06
- **Files changed:** `edge/eval/u06_rate_summary.py` (new), `edge/tests/test_u06_rate_summary.py` (new). No existing file modified — `EpisodeRecord`, `TransitionRecord`, `active_injection_labels`, `edge/rl/reward.py`, `edge/rl/fallback_gate.py`, `edge/rl/policy.py`, `edge/eval/rl_training.py`, environment transition logic, and every hardware/driver/actuator/relay/GPIO file are untouched.

**What this increment does:**
- Adds a pure function, `summarize_episode_rates(record: EpisodeRecord) -> EpisodeRateSummary`, computing axis (i)'s already-proposed, proxy-based rates exactly per the "U06 — Operational Definitions Proposal" sections A–C above: false isolation (`safety_status == "nominal"` and `requested_action` is `isolate`/`reduce_weight`) and missed critical fault (`safety_status == "isolation_active"` and `requested_action` is `continue_`), each with its own opportunity denominator, reporting `rate=None` (never `0.0`) when its denominator is zero.
- Per section F, `safe_stop` requests, fallback/unvalidated `policy_status`, and world-inert approved actions are **not excluded** from the opportunity denominators — section F's own text states these definitions "still evaluate the requester's intent," warning that exclusion could produce a misleadingly clean rate. Instead each is reported as its own breakdown field (`safe_stop_request_count`, `policy_status_breakdown`, and two world-inert-approved-action counts scoped to each denominator) alongside the rate.
- Scenario/baseline identity (`scenario_name`, `baseline_name`), `step_count`, and `termination_cause` are carried through unchanged from the input `EpisodeRecord`.

**What this increment explicitly does NOT do:**
- Does not implement axis (ii) (tracker-vs-injection agreement) or axis (iii) (ground-truth-anchored rates) — both remain unimplemented, open proposals from the preceding scoping review.
- Never reads the injection-ground-truth field `TransitionRecord` separately carries, and never imports anything from the injection-framework package — the new module's own source is scanned by a dedicated test confirming this.
- Chooses no acceptable threshold, computes no verdict, and makes no claim of validation, safety, accuracy, or production readiness anywhere — confirmed by a dedicated source-scan test.
- Changes no reward, gate, policy, transition, or DQN behavior — the function only reads an already-produced `EpisodeRecord`, never constructs or calls the environment/gate/reward/policy modules.

**Not done by this increment:** U06's status in the UNDECIDED list above is unchanged: fully open, zero partial resolution. Axes (ii) and (iii) remain unimplemented proposals/open questions, as does any acceptable-rate decision.
