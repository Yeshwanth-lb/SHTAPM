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
- U05 — `divergence_threshold` + substitution uncertainty-cap values (P3). **Partial:**
  behavioral design resolved by D018 (divergence computation form, recovery rule,
  60s-expiry escalation, uncertainty interface, cycle sequencing); uncertainty-
  estimation method resolved provisionally by D019 (deterministic
  elapsed-substitution-time proxy, single-signal, no reconstruction-stability
  or divergence input). **Still open:** both numeric values themselves
  (data-gated), and the time→uncertainty scaling formula (D019, not chosen).
- U06 — RL reward shaping + acceptable false-isolation rate (P3).
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
