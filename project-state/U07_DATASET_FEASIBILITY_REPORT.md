# U07 Dataset Feasibility Report — SWaT vs. WADI

**Date:** 2026-08-24
**Type:** Research / feasibility analysis only — NO code changes, NO downloads, NO commits
**Scope:** Determine which real ICS dataset (SWaT or WADI) is suitable for U07 validation of the existing P2 architecture

**Source-rigor discipline:** I do not have dataset access (iTrust is request-gated; consistent with `P2_RESUME.md` §5 U07 row). Every factual claim below is tagged:
- **[VERIFIED]** — read directly from an authoritative primary source I fetched myself this session (the official iTrust dataset-characteristics page, or the full text of a peer-reviewed/arXiv paper rendered via ar5iv). Not a search-engine summary.
- **[INFERRED]** — a reasonable synthesis from convergent secondary sources (multiple independent search results agreeing) or from standard ICS/SCADA naming convention, but not confirmed by a primary document I personally read.
- **[UNCONFIRMED]** — appeared in only a search-engine-generated summary (not a document I fetched and read directly), a single weak source, or could not be corroborated at all. Treated as **not established** — reported only because it recurred in the research trail, not because it is trustworthy.

**I did not invent any column/tag name.** Where I could not verify an exact tag name against a primary source, I say so explicitly rather than presenting a plausible-looking name as fact. Several PDF fetches this session returned corrupted/binary content and yielded nothing usable — those are noted, not silently discarded.

---

## 1. Executive Summary

**Central, well-supported finding: neither SWaT nor WADI natively contains our six bench channels as physically defined.** Both are water-treatment/distribution **SCADA process-variable** datasets — level, flow, differential pressure, water-chemistry analyzers, and discrete valve/pump state **[VERIFIED general categories; INFERRED per-tag names — see §2–3]**. Neither is documented anywhere I could access as containing a continuous **motor current** (amps) signal or a **vibration/accelerometer** signal — the two variables our `k` provider's current↔vibration heuristic needs **[VERIFIED absence on the official SWaT and WADI characteristics pages I fetched directly; INFERRED absence more broadly from converging secondary sources]**. **Temperature, humidity, and gas** tags were not found or confirmed in any source reviewed **[UNCONFIRMED — absence, not presence, and not from a primary document enumerating the full tag list]**. The one plausible overlap is **pressure**, but SWaT/WADI pressure tags (where they exist) measure **in-process water pressure**, not the **atmospheric** pressure our bench sensor reads — the same class of mismatch already flagged for the bench side (§11).

**Important caveat discovered this session:** the **official iTrust SWaT dataset-characteristics page states directly** that the complete sensor/actuator tag list is documented in a `readme.docx` bundled with the dataset itself — **not published on the public web** **[VERIFIED]**. This means the specific per-process tag names circulating in secondary literature (`LIT101`, `MV101`, `FIT301`, etc.) could not be independently confirmed by me against a primary iTrust document this session; I found and could quote directly only **one** tag (`LIT101`) from the official page itself. Everything else attributed to specific SWaT tag names in this report is marked **[UNCONFIRMED]** and should be re-verified once dataset access is obtained.

**Consequence:** SWaT/WADI can validate the P2 **software architecture and detection/trust methodology** (IsolationForest behavior on real non-stationary data, Beta-trust math, the deferred normalization-choice decision, ChannelFlagPolicy's variance-threshold algorithm on real signals, O10 ablation reporting) using the **dataset's own channels as a substitute schema**. They **cannot** validate our **literal six-channel semantics**, our **current↔vibration `k` definition**, or **O3** (which the PRD explicitly ties to "labelled bench scenarios," not SWaT/WADI).

**Recommendation:** **SWaT primary, WADI fallback**, used explicitly as *methodology validation*, kept separate from — and not a substitute for — the still-mandatory real bench validation.

---

## 2. SWaT Signal Inventory

**[VERIFIED — official iTrust dataset-characteristics page, fetched directly]**
- SWaT is a water-treatment testbed; the dataset covers **all values from 51 sensors and actuators**.
- The page explicitly states: *"SWaT.A1 — 11 days of continuous operation: 7 under normal operation and 4 days with attack scenarios."*
- The page also documents **additional, shorter SWaT variants**: *"SWaT.A4 & A5 — 3 hours of SWaT running under normal operating condition and 1 hour during which 6 attacks were carried out"* and *"SWaT.A6"* with the same structure. **This means "SWaT" is not a single dataset but a family of releases with different durations/attack counts** — relevant when scoping a dataset-access request.
- The page names exactly **one** specific tag directly: `LIT101`, in the context of a maintenance-drainage anomaly ("the first 30 minutes of LIT101 data exhibits change even though there was no water in/outflow").
- The page states the **full tag-by-tag documentation is in a `readme.docx` file bundled with the dataset**, not published on the public site.
- **The page does not mention any motor-current or vibration sensor.**

**[INFERRED — recurring across multiple independent secondary sources, not confirmed by a primary document]**
- SWaT comprises **six sequential processes** (P1 raw-water intake, P2 chemical dosing, P3 ultrafiltration, P4 dechlorination/UV, P5 reverse osmosis, P6 UF backwash/permeate transfer), each with its own PLC.
- Tag-prefix convention: `LIT` = level, `FIT` = flow, `PIT` = pressure, `DPIT` = differential pressure (across the UF membrane), `AIT` = water-chemistry analyzer (pH/ORP/conductivity/turbidity — **not** an ambient "gas" sensor), `MV` = motorized valve (discrete state), `P` = pump (discrete on/off state), `UV` = dechlorination lamp.
- Total sensor/actuator split reported inconsistently across secondary sources as either "25 sensors + 26 actuators" or "26 sensors + 25 actuators" — the total of 51 is consistent, but I could not resolve which split is correct from a primary source.
- 1 Hz sampling rate.
- **36 distinct attacks** across the 4-day attack period (SWaT.A1 variant), by Goh, Adepu, Junejo & Mathur.

**[UNCONFIRMED — search-summary only, NOT independently verified against a primary document; do not treat as authoritative]**
- Per-process tag examples that appeared only in AI-generated search summaries: `MV101`, `P101`, `P102` (P1); `DPIT301`, `FIT301`, `LIT301`, `MV301`–`MV304`, `P301`, `P302` (P3); `AIT401`, `AIT402`, `FIT401`, `LIT401`, `P401`–`P404`, `UV401` (P4); `AIT501`–`AIT504`, `FIT501`–`FIT504`, `P501`, `P502`, `PIT501`–`PIT503` (P5); `FIT601`, `P601`–`P603` (P6). P2-stage tags were not surfaced at all in any source reviewed.
- These names are **plausible and consistent with the inferred naming convention above**, but I did not read them in a primary document myself, and one search summary in this same research trail (§13) was independently caught mixing SWaT-style and WADI-style tag names incorrectly — a concrete reason not to trust search-summary tag lists at face value.

**Bottom line for §2:** the *category* of signals in SWaT (level, flow, pressure/differential-pressure, water-chemistry, discrete valve/pump state) is well-supported. The *exact column headers* are not publicly documented outside the dataset's own bundled `readme.docx`, and should be treated as unverified until that file is obtained.

---

## 3. WADI Signal Inventory

**[VERIFIED — official iTrust dataset-characteristics page, fetched directly]**
- WADI testbed data: **"16 days of continuous operation: 14 under normal operation & 2 days with attack scenarios,"** covering **"all 123 sensors and actuators."**
- **"15 attacks were launched during the 2 days"** of the attack period.
- The page does not enumerate individual tag names, physical types, or grid assignments; it does not mention motor-current or vibration sensors.

**[VERIFIED — arXiv:1906.02279, Adepu & Mathur, "Investigation of Cyber Attacks on a Water Distribution System," fetched and read via ar5iv (full paper text, not a search summary)]**
- WADI is organized into **three control processes/grids**, each with its own PLC set: **primary grid, secondary grid, return-water grid**. The paper states the primary grid's input can be derived from SWaT's output (WADI is downstream of/complementary to SWaT).
- **Tag naming convention is grid-prefixed with underscores**: e.g. `1_LT_001`, `2_LT_002`, `1_MV_001`, `1_MV_002`, `1_AIT_002`, `2_MV_003`, `2_MCV_101`, `2_MCV_201`. This is confirmed **directly from the paper's own attack-description table**, not inferred.
- Six specific attacks are described in detail in this paper, with these exact tags as targets:
  1. `1_LT_001` (level) — simulated tank overflow, blocking supply.
  2. `2_LT_002` (level) — false empty-reservoir reading, risking pump damage.
  3. `1_MV_002` (motorized valve) — forced open, causing water drainage/supply interruption.
  4. `1_MV_001` (motorized valve) — forced closed, stopping inflow to the raw-water tank.
  5. `1_AIT_002` (water-quality analyzer) + `2_MV_003` (valve) — coordinated two-point attack causing contaminated water to reach the reservoir.
  6. `2_MCV_101` + `2_MCV_201` (control valves) — coordinated two-point attack causing intermittent consumer supply.
- **The paper documents no motor-current or vibration tag among the attacks it describes.**

**[INFERRED — from secondary sources, consistent with but not verbatim from the primary sources above]**
- Sensor categories present: water **level** (`LT`/`LIT`), **flow** (`FIT`/`FIC`), **differential pressure** (`DPIT`), water-**quality/chemical analyzers** (`AIT` — pH, turbidity, conductivity, residual chlorine), discrete **pump** (`PU`) and **motorized/control valve** (`MV`/`MCV`) actuator states.
- Attack durations of **2–30 minutes** — shorter than SWaT's.

**[UNCONFIRMED]**
- The **remaining ~9 of the 15 total WADI attacks** — the paper I directly read described 6 in detail; I could not locate a source enumerating all 15 with the same rigor.
- The **complete 123-tag inventory** — only 8 specific tags were confirmed via direct primary-source reading (§ above); the other ~115 remain undocumented in any source I accessed.
- WADI's exact per-tag sampling rate (commonly assumed comparable to SWaT's 1 Hz, but not confirmed for WADI specifically in any source read this session).

**Bottom line for §3:** WADI's *organizational structure* (3 grids, naming convention) and a *small, specific subset* of its tags (8 of 123) are genuinely verified via direct primary-source reading — a stronger evidentiary basis than most of the SWaT tag claims in §2. The *full* 123-tag inventory remains unconfirmed.

---

## 4. Six-Channel Mapping

| Our channel | SWaT | WADI | Verdict |
|---|---|---|---|
| **temperature** | Not found in any source, verified or otherwise | Not found in any source, verified or otherwise | **No match found.** This is an absence-of-evidence finding, not a confirmed absence — the full tag lists for both datasets are gated (readme.docx / 115 unconfirmed WADI tags). Requires raw data-dictionary access to settle definitively. |
| **pressure** | `PIT`/`DPIT` tags **[INFERRED]** exist and, per the general SWaT process description **[INFERRED]**, measure in-process water/membrane pressure | `DPIT`/`PIT` referenced in general description **[INFERRED]**, not confirmed via the 8 directly-verified tags | **Mismatch, not a match, even where present.** Our bench pressure sensor is explicitly **atmospheric**, not water-line (project constraint, §11). Any SWaT/WADI pressure tag measures a different physical quantity than our bench channel. Must not be silently equated. |
| **humidity** | Not found in any source | Not found in any source | **No match found.** Ambient humidity is not a conventional water-treatment/distribution SCADA process variable; its absence is more plausible here than for temperature, but still not confirmed as a deliberate exclusion (just unattested). |
| **gas** | `AIT` tags **[INFERRED]** exist but measure **aqueous water chemistry** (pH, ORP, conductivity, turbidity, chlorine), not an ambient/gas-detector reading | Same `AIT` water-chemistry semantics **[INFERRED]** | **No match.** Even if an `AIT`-family tag were confirmed, it measures a different physical phenomenon (dissolved/aqueous chemistry) than a bench "gas" sensor would (presumably ambient air quality or a specific gas concentration). Treating them as equivalent would be inventing a mapping, not finding one. |
| **current** (motor electrical draw, amps) | **[VERIFIED absent]** — official page confirms only "sensors and actuators," no current tag mentioned; actuator state for pumps is a discrete on/off `P` reading per **[INFERRED]** convention, not continuous amperage | **[VERIFIED absent]** — official page and the directly-read attack paper both describe pump actuators (`PU`) only as discrete on/off/attack-target state | **No match — the strongest, best-evidenced negative finding in this report.** Confirmed absent from both official pages I fetched directly. |
| **vibration** | **[VERIFIED absent]** — not mentioned on the official page or in any source reviewed | **[VERIFIED absent]** — same | **No match.** Neither testbed is a motor-condition-monitoring system; both are hydraulic-process SCADA. |

**Bottom line:** Of six channels, **zero have a confirmed, physically faithful match** in either dataset. Pressure is the closest *nominal* overlap where present, but carries a documented physical-meaning mismatch. Current and vibration are the two channels with the strongest (most directly source-verified) confirmed absence.

**Aside, out of scope for this recommendation:** search surfaced a *different, unrelated* dataset — "Motor current and vibration monitoring dataset for various faults in an E-motor-driven centrifugal pump" (PMC-indexed) **[UNCONFIRMED — title/existence only, not read]** — which nominally *would* contain the current+vibration pair `k` needs, but has no cyber-attack labels and is not an ICS-security dataset. Noted only for completeness; not evaluated further and not recommended for U07 as scoped.

---

## 5. Current ↔ Vibration `k` Validation Feasibility

**Cannot validate on SWaT. Cannot validate on WADI.** This is the most confidently-supported conclusion in this report — both official iTrust pages, fetched and read directly, describe only water-process sensors and discrete actuator states; neither mentions motor current or vibration instrumentation anywhere.

Our `k_correlation.py` provisional rule assumes a **rotating-machinery condition-monitoring relationship**: motor current draw and mechanical vibration trending together under load, for a **single pump/motor**. This is a different physical domain from what SWaT/WADI instrument — **hydraulic process state** (levels, flows, membrane differential pressure, water chemistry) and **discrete actuator commands**, not the **electrical/mechanical condition of the pump itself**.

Per the instruction not to assume correlation merely because two signals exist: this session found that **neither signal exists at all** in either dataset (to the extent I could verify), so there is nothing to test the correlation against — the question is moot, not merely unproven.

**What SWaT/WADI could offer instead (a different, not-yet-decided claim):** both datasets likely contain *other* physically-coupled sensor pairs within a single hydraulic stage (e.g., a level/flow/differential-pressure relationship within one SWaT process) that the invariant-based-detection literature is known to exploit **[INFERRED — general awareness that such literature exists, not independently verified against a specific paper this session]**. Using such a pair to validate the *general mechanism* of cross-sensor consistency checking (not our literal `k`) would require **defining a new relationship**, which is explicitly out of scope here (§12 instruction: do not propose architecture changes). Noted only for transparency, not proposed.

---

## 6. P2 Acceptance-Criteria Coverage

| Criterion | Requirement (from `docs/SHTAPM_PRD-4.md`) | SWaT | WADI | Reasoning |
|---|---|---|---|---|
| **P2-ANOM-H2** | Injected spike fault → flagged ≤3 windows, attribution=fault | Partially validate | Partially validate | Both datasets contain labeled sensor-manipulation attacks with a fault-like signature. Detection/attribution **mechanics** can be exercised, but only on dataset-native channels, and neither dataset provides an organic-fault-vs-cyber-attack ground-truth pair (every labeled event is an attack by construction). |
| **P2-ANOM-H3** | Injected constant-spoof attack → flagged ≤3 windows, attribution=attack | Partially validate | Partially validate | Both include forced/pinned-value manipulations (constant-spoof-like — e.g., WADI's `1_LT_001`/`2_LT_002` forced readings, directly verified §3). Same caveat as H2: dataset-native channels, and "attribution=attack" is true by label construction, not independently derived the way it would need to be on the bench. |
| **P2-ANOM-E2** | Simultaneous fault + attack on different channels → both flagged, attributed independently | Partially validate | Partially validate (slightly stronger) | Neither stages an organic-fault + concurrent-attack pair. WADI's directly-verified **multi-point coordinated attacks** (`1_AIT_002`+`2_MV_003`; `2_MCV_101`+`2_MCV_201`) are the closest available proxy for "two channels disturbed at once," but both are attacks, not fault+attack — approximating the literal criterion would require combining a dataset attack with our own injection framework. |
| **P2-TRUST-H2** | Spoofed sensor → trust <0.4 within ≤3 windows | Partially validate | Partially validate | Beta-trust math and forgetting-factor mechanics can be exercised against real spoof-style attacks via a dataset-native `c`-style residual. Since `k` is undefined for any dataset channel (§5), trust drop would rely almost entirely on `c` (and `h`), not the full `g=0.4c+0.3k+0.3h` design — tests the trust **engine**, not the full intended **signal composition**. |
| **P2-TRUST-E2** | Two correlated channels both drift → correlation term doesn't falsely exonerate | Cannot validate | Cannot validate | Requires `k`'s pairing to exist and be exercised; confirmed absent (§5). A different dataset-native pair would require redefining `k` — out of scope. |
| **P2-TRUST-S1** | Collusive attack on 2 channels fakes correlation → `h` prevents full trust | Cannot validate (for the `k`-collusion mechanism) / Partially validate (for `h`'s EMA mechanism tested in isolation) | Same | The collusion-via-correlation scenario is bound to `k`'s specific pair, absent here. `h`'s EMA could be exercised against any repeatedly-flagged dataset channel in isolation, but that doesn't test the criterion as written. |
| **O3** (≥85% attribution accuracy) | PRD: *"≥ 85% attribution accuracy **on labelled bench scenarios**; confusion matrix reported"* | **Cannot validate** | **Cannot validate** | Not a data-availability gap — the PRD text itself scopes O3 to bench scenarios. No dataset choice changes this. |
| **O10** (confusion matrix / ablations) | PRD: *"Results reported **on SWaT/WADI** with ablations vs. baselines"* | **Can validate** | **Can validate** | The one PRD objective explicitly scoped to SWaT/WADI. SWaT favored for the volume of published comparable baselines (§9). |

**Summary:** No criterion is **fully** satisfiable by either dataset alone under the current channel architecture. Most are **partially** satisfiable as architecture/methodology exercises. `P2-TRUST-E2` and `P2-TRUST-S1` are **not** satisfiable without a `k` redefinition (out of scope). `O3` is **explicitly** bench-only per PRD wording. `O10` is the one criterion cleanly satisfiable by dataset work as written.

---

## 7. Healthy Baseline Availability

**[VERIFIED — official iTrust pages]**
| Dataset | Normal-operation duration | Approx. rows (at inferred 1 Hz) | Notes |
|---|---|---|---|
| SWaT.A1 | 7 days | ~604,800 timestamps **[INFERRED — 1 Hz sampling rate is from secondary sources, not confirmed on the official page I fetched]** | Standard baseline window used across the SWaT literature. |
| SWaT.A4/A5/A6 | 3 hours | ~10,800 timestamps (if 1 Hz) | Much shorter alternative variant — likely insufficient alone for robust IF/consistency baseline fitting, but noted since it exists. |
| WADI | 14 days | ~1.2M timestamps **[INFERRED sampling rate, not confirmed for WADI specifically]** | Largest baseline window of the two by duration. |

Both SWaT.A1 and WADI are large enough in **volume** (assuming ~1 Hz) for IsolationForest baseline fitting, `ConsistencyProvider` mean/std + empirical-CDF calibration, and general normalization calibration. **Neither baseline's stationarity, drift, or missing-value characteristics were evaluated this session** — that requires the raw files.

---

## 8. Attack/Label Availability

**[VERIFIED — official iTrust pages]**
| Dataset | Attack window | # attacks | Documentation depth (this session) |
|---|---|---|---|
| SWaT.A1 | 4 days | 36 (Goh/Adepu/Junejo/Mathur) | Category-level only — I could not directly read a primary source enumerating all 36 by name/target this session. |
| SWaT.A4/A5/A6 | 1 hour | 6 each | Same limitation. |
| WADI | 2 days | 15 | **6 of 15 directly read and confirmed** (§3), with exact target tags and physical impact. Remaining 9 unconfirmed. |

**Represented attack types (general pattern, both datasets, per what I directly verified for WADI and what is broadly consistent with the SWaT literature):** single-point sensor-value manipulation (forced/pinned readings — FDI/constant-spoof-like), actuator forced-state attacks (valve/pump forced open/closed/on/off), and multi-point coordinated attacks. This general *class* matches what `edge/injection/` already models (constant-spoof, bias/ramp FDI) — encouraging for methodology transfer, independent of the channel mismatch.

---

## 9. SWaT vs. WADI Comparison

| Dimension | SWaT | WADI |
|---|---|---|
| Sensor relevance to our 6 channels | Low — no current/vibration confirmed present (verified absent); temperature/humidity/gas not found; pressure mismatched in physical meaning | Low — same gaps; larger tag count doesn't add the missing physical quantities |
| Attack labels | 36 attacks (A1) — richest count, but I could not directly verify the full by-name list this session | 15 attacks — smaller count, but 6 of 15 directly verified with target tags and impact, a stronger evidentiary basis than what I obtained for SWaT's list |
| Physically related signal pairs (for any future k-redefinition, out of scope now) | **[INFERRED]** likely richer — single-stage treatment process, widely cited in invariant-based-detection literature | **[INFERRED]** likely weaker — distribution-network topology across 3 grids is more loosely coupled |
| Suitability for our 6-channel architecture | Poor (confirmed) | Poor (confirmed), equally |
| Suitability for k validation (current↔vibration, as literally defined) | Not suitable (verified) | Not suitable (verified) |
| Suitability for attribution methodology | **[INFERRED]** larger surrounding literature to compare against | **[INFERRED]** smaller surrounding literature |
| Suitability for trust (Beta/c/h) engine validation | Good — 7-day clean baseline, well-characterized top-level structure | Good — 14-day clean baseline (larger), but attack documentation less complete in what I could verify |
| Preprocessing complexity | Lower — 51 tags vs. WADI's 123, single official page confirms structure | Higher — 123 tags across 3 grids; **[UNCONFIRMED]** — several secondary sources described WADI as noisier/harder to preprocess than SWaT, but I did not independently verify this against raw files |
| Expected adaptation effort | Lower (fewer tags, smaller data volume) | Higher |

---

## 10. Primary + Fallback Recommendation

- **Primary: SWaT.** Smaller (51 vs. 123 tags), the official page itself is easier to reason about, and it has the most extensively cited surrounding literature for comparative O10 ablation reporting. The `SWaT.A1` variant (7 days normal + 4 days attack, 36 attacks) is the appropriate one to request — note the shorter `A4/A5/A6` variants exist but are unlikely to be sufficient alone.
- **Fallback: WADI.** Larger scale (123 tags, 14-day baseline), and — notably — this session obtained **stronger direct verification of specific WADI attack details** (6 of 15, with exact tags) than for any specific SWaT attack. Its multi-point coordinated attacks are the closest (still imperfect) proxy for `P2-ANOM-E2`-style simultaneous-channel methodology testing.

This concerns **which dataset to request access to first** — it is not a claim that either will validate the bench-specific architecture (§11).

---

## 11. U07 Validation Scope

### A. What U07 (SWaT primary) CAN validate
- Whether **IsolationForestDetector** (`iforest.py`) behaves sanely on real, non-stationary industrial time series instead of the simulator's stationary independent-Gaussian channels — using SWaT's own tag schema as the input feature space, not our six channels.
- Resolution of the **explicitly deferred normalization-choice decision** in `P2_RESUME.md` §5 (per-window min-max vs. train-fit/global vs. z-score) — this needs real non-stationary data, which SWaT provides.
- **IsolationForest hyperparameter + `flag_threshold` tuning methodology** (the process, not the final bench numbers).
- **Beta-trust engine mechanics** (`TrustEngine`, `beta.py`) exercised against real per-window `g` values from a dataset-native `c`-style residual.
- **ChannelFlagPolicy's variance-threshold algorithm** exercised on real windows — sanity of behavior, not correctness of bench-channel localization.
- **O10** — the one PRD objective explicitly scoped to SWaT/WADI.
- General pipeline robustness against real-world timing/noise/formatting the simulator doesn't produce.

### B. What still requires REAL BENCH/pump data
- The literal **current↔vibration `k` relationship** — confirmed absent from both datasets' public documentation.
- Validation of our **six channels as literally named** (temperature, atmospheric pressure, humidity, gas, current, vibration) — no confirmed clean mapping in either dataset (§4).
- **O3** — PRD explicitly requires "labelled bench scenarios."
- **P2-ANOM-H2/H3/E2** and **P2-TRUST-H2** *as literally written against our six channels*.
- **Final** IsolationForest/`flag_threshold` calibration for the bench's actual sensor noise.
- Whether the bench's atmospheric pressure sensor provides any usable proxy signal at all — a bench-only question.

### C. What still requires domain/physics validation
- Whether current↔vibration trend-sign consistency is a valid invariant for *this* pump at bench scale — needs domain-expert review or a purpose-built motor-condition dataset (§4 aside), separately from ICS-attack validation.
- Whether `ChannelFlagPolicy`'s variance-threshold heuristic has a principled causal connection to fault/attack origin, versus merely correlating with "which channel moved most" — needs bench ground truth or domain review.
- Whether treating atmospheric pressure as a legitimate proxy channel is acceptable — engineering/domain decision, not a data question.

### D. What CANNOT be claimed from dataset-only experiments (regardless of dataset)
- That our six bench channels behave as validated in production — dataset work validates **software/architecture** using **substitute channels**.
- That the current↔vibration `k` definition is physically valid — confirmed absent from both datasets' documentation.
- That **O3** is satisfied — textually bench-bound in the PRD.
- That `ChannelFlagPolicy` reliably attributes *real bench* faults/attacks to the correct one of our six channels.
- That **P2 acceptance is complete**.

---

## 12. Remaining Bench/Physics-Gated Items

(Consolidated from §11.B/C — nothing new added.)
1. Real pump current↔vibration relationship — bench + possibly a dedicated motor-condition dataset.
2. Real six-channel semantics on the bench — no public ICS substitute found.
3. O3 bench-scenario attribution accuracy — bench-only per PRD text.
4. P2-ANOM-H2/H3/E2, P2-TRUST-H2 as literally written — bench-only.
5. Final IF/`flag_threshold` tuning for bench sensor noise — bench-only.
6. Atmospheric-pressure-as-proxy validity — bench/domain-only question.
7. Causal (not merely statistical) grounding for `ChannelFlagPolicy`'s variance heuristic — bench ground truth or domain review.

---

## 13. Risks and Assumptions

- **Access risk:** iTrust access remains request-gated with unknown lead time (unchanged from `P2_RESUME.md` §5). This report assumes access *could* be requested; it does not confirm access has been granted.
- **SWaT tag inventory is largely unconfirmed:** the official page itself defers detailed tags to a `readme.docx` bundled with the dataset. Most specific SWaT tag names in §2 are marked `[UNCONFIRMED]` and must be re-verified once that file is obtained — **do not treat them as ground truth in downstream planning.**
- **WADI tag inventory is partially confirmed, mostly not:** 8 of 123 tags were directly verified via a primary source; the remaining ~115 were not found in any source accessed this session.
- **Secondary-source unreliability observed directly:** one AI-generated search summary conflated SWaT-style flat tag names (`MV-101`, `LIT-101`) with a WADI attack-scenario description, when WADI's actual, directly-verified convention uses grid-prefixed names (`1_LT_001`, `2_MV_003`). I filtered this specific instance out, and it is the concrete reason this rewrite is far more conservative about which tag names are marked `[VERIFIED]` versus `[UNCONFIRMED]`.
- **Several PDF fetches failed outright** this session (returned corrupted/binary content, not usable text) — including the CISPA statistical-analysis paper and the SUTD technical design report (redirected to the generic iTrust homepage). These are not silently dropped; their absence of contribution is reflected in what remains `[UNCONFIRMED]` above.
- **Sampling-rate assumption:** 1 Hz for both datasets is an `[INFERRED]` carry-over from general ICS-dataset literature, not confirmed on either official page I fetched directly.
- **"Noisier WADI" claim:** recurs across secondary sources but was not independently reproduced against raw files — `[UNCONFIRMED]`.
- **TEP fallback context:** `P2_RESUME.md` §5 records TEP (Tennessee Eastman Process) as the documented substitute if iTrust access fails. TEP is a chemical-process simulation with no water-specific tags — likely an even larger channel mismatch than SWaT/WADI. Noted for completeness, not evaluated in depth (out of the SWaT-vs-WADI scope requested).
- **Absence claims (current/vibration) are the most reliable finding in this report** — confirmed absent on both official iTrust pages I fetched and read directly, which is a stronger evidentiary basis than most of the positive tag claims above.

---

## 14. Final Recommendation

1. **Primary dataset for U07: SWaT** (specifically the `SWaT.A1` variant — 7 days normal / 4 days attack / 36 attacks). Smaller, and its official characteristics page is directly readable, even though the full tag dictionary itself is dataset-bundled, not public.
2. **Fallback dataset: WADI.** Larger scale, longer baseline, and — notably — this session's strongest directly-verified attack evidence (6 of 15 attacks, with exact target tags) came from WADI, not SWaT. Its multi-point coordinated attacks are the closest available proxy for simultaneous-channel methodology testing.
3. **U07 on either dataset validates architecture and methodology — not the bench's six channels, not `k`, not O3.** This is a hard boundary set by what these datasets actually measure (to the extent verifiable), not a shortfall of research effort. Treat U07-on-SWaT/WADI and bench validation as **two separate, both-still-required tracks**; never present SWaT/WADI results as bench-equivalent evidence.
4. **Before requesting dataset access, obtain the official tag dictionary/readme** for whichever dataset is chosen — this report's own §2/§3 confirm that the authoritative per-tag list is not public, and most tag names cited in secondary literature (and in this report) remain `[UNCONFIRMED]` until that document is in hand.
5. **No architecture change is proposed here.** If there is later appetite to redefine `k` for a dataset-native physically-coupled pair purely to exercise the general cross-sensor-consistency *mechanism* on real data, that is a distinct design decision requiring separate approval — not inferred or adopted from this report.

**Awaiting approval before any next step** (dataset access request, further research, or scoping a SWaT-based methodology-validation plan).
