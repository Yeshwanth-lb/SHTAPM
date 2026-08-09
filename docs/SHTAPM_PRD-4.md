# Product Requirements Document (PRD)
# SHTAPM — Self-Healing Trust-Aware Predictive Maintenance for Adversarially Resilient Industrial IoT

**Application domain:** Remote / unmanned water & wastewater pumping infrastructure (SCADA/ICS cyber-physical system)
**Physical demonstrator:** Bench-scale water-pump rig with six live sensor channels
**Document owner:** Yeshwanth L B — Major Project (SHTAPM), BMS College of Engineering
**Status:** Development-ready · **Version:** 1.0 · **Classification:** Internal

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Background & Motivation](#2-background--motivation)
3. [Product Vision](#3-product-vision)
4. [Objectives](#4-objectives)
5. [Stakeholders](#5-stakeholders)
6. [User Personas](#6-user-personas)
7. [User Stories](#7-user-stories)
8. [Functional Requirements](#8-functional-requirements)
9. [Non-Functional Requirements](#9-non-functional-requirements)
10. [System Architecture (Hardware + Software)](#10-system-architecture)
11. [Features Breakdown](#11-features-breakdown)
12. [Data Requirements & Telemetry](#12-data-requirements--telemetry)
13. [Literature Survey Insights](#13-literature-survey-insights)
14. [Competitive / Existing Solution Analysis](#14-competitive--existing-solution-analysis)
15. [Assumptions](#15-assumptions)
16. [Constraints](#16-constraints)
17. [Risks & Mitigation](#17-risks--mitigation)
18. [Hardware Demo & Setup Guide](#18-hardware-demo--setup-guide) *(Custom)*
19. [Testing Strategy Overview](#19-testing-strategy-overview)
20. [Phase-Wise Implementation with Exhaustive Test Cases](#20-phase-wise-implementation-with-exhaustive-test-cases)
21. [Acceptance Criteria](#21-acceptance-criteria)
22. [Future Enhancements](#22-future-enhancements)
23. [Developer Handoff Summary (One-Pager)](#23-developer-handoff-summary-one-pager)
- [Appendix A: Missing Information Checklist](#appendix-a-missing-information-checklist)
- [Appendix B: Questions to Clarify Before Development](#appendix-b-questions-to-clarify-before-development)
- [Appendix C: Feature Priority Matrix (MoSCoW)](#appendix-c-feature-priority-matrix-moscow)
- [Appendix D: Bill of Materials (BOM)](#appendix-d-bill-of-materials-bom) *(Added)*
- [Appendix E: Security & Authentication](#appendix-e-security--authentication) *(Added)*
- [Appendix F: Data Flow Diagram Notes](#appendix-f-data-flow-diagram-notes) *(Added)*
- [Final: Development-Ready PRD Summary](#final-development-ready-prd-summary)

---

## 1. Executive Summary

SHTAPM is a cyber-physical monitoring and self-healing system for remote, unmanned water/wastewater pumping stations. It keeps a pump correctly monitored and safely running when a sensor either **fails** (drift, spike, death) or is **falsified** (false-data-injection, replay, spoofing) — attributing which of the two is happening, isolating the untrustworthy sensor, reconstructing its signal so health prediction never goes dark, and logging every decision to a tamper-evident ledger. No human is required in the loop.

The deliverable is twofold: (a) a **bench-scale hardware demonstrator** — a 12 V pump instrumented with six live sensor channels on a Raspberry Pi 4 edge node — and (b) an **enterprise-grade admin web dashboard** that streams live telemetry, trust scores, health/RUL, RL decisions, and ledger events in real time over MQTT→WebSocket, visualized to a standard indistinguishable from a professionally developed SaaS product.

The core novelty is **cyber-physical disambiguation with autonomous self-healing**: prior art does *either* predictive maintenance *or* intrusion detection; SHTAPM does both and, critically, keeps operating through a compromised sensor set rather than merely raising an alert. The system is validated on the public SWaT/WADI water-treatment attack datasets (primary quantitative evaluation) and demonstrated live on the pump rig (qualitative proof).

This PRD is the single source of truth for building, integrating, testing, and demonstrating that system end to end.

---

## 2. Background & Motivation

**The problem.** Industrial sensor networks fail in two ways that look identical but demand opposite responses. A sensor that is physically dying and a sensor that is being actively spoofed both produce anomalous readings; a naive detector treats them the same and mitigates wrongly — re-calibrating a compromised sensor, or isolating a merely-noisy one. In critical infrastructure this ambiguity is dangerous.

**Why water/wastewater.** Remote pumping and lift stations are genuinely unmanned, monitored over telemetry, and often not quickly reachable. A stopped clean-water pump interrupts supply; a stopped wastewater lift station causes sewage backup or overflow — a public-health and environmental event. Sensor falsification here is not hypothetical: the 2021 Oldsmar, Florida water-treatment intrusion altered a chemical-dosing setpoint, and the SWaT/WADI research testbeds provide real, labelled physical attacks on water systems. This is the rare domain where the threat is documented, a gold-standard dataset exists, and the entire scenario can be reproduced on a lab bench.

**The gap.** Existing systems (see §13–14) address single threat vectors, use static rule-based trust, require manual reconfiguration after an incident, and log raw network traffic rather than high-level decision provenance. SHTAPM closes all four.

**Scope of this document.** A buildable, testable, demonstrable system — not a production ICS deployment. Where the bench rig is a scale proxy for a real pumping station, this is stated explicitly and honestly.

---

## 3. Product Vision

> *A pumping station that no one can reach should be able to keep watching over its own health, tell the difference between a sensor that is broken and one that is lying, heal around the bad input on its own, and prove — immutably — everything it decided.*

SHTAPM's north star is **continuity of trustworthy monitoring under compromise**. Success is not "we detected the attack" — many systems do that. Success is "the pump kept running and kept being predicted correctly, autonomously, and we can prove every decision after the fact."

The dashboard vision is equally deliberate: an operator (or an examiner) should look at the screen and believe they are looking at a commercial industrial-monitoring product, not a student prototype — real-time, responsive, information-dense but legible, and visibly reacting to physical events on the bench within a heartbeat.

---

## 4. Objectives

| # | Objective | Measure of success |
|---|-----------|--------------------|
| O1 | Ingest six live sensor channels from the pump rig | All six channels stream at 1 Hz with < 1% dropped samples over a 10-min run |
| O2 | Detect anomalies in real time | Injected fault/attack flagged within ≤ 3 sampling windows |
| O3 | Attribute anomaly as fault vs. attack | ≥ 85% attribution accuracy on labelled bench scenarios; confusion matrix reported |
| O4 | Maintain per-sensor dynamic trust scores | Trust of a spoofed sensor drops below 0.4 within ≤ 3 windows; recovers when clean |
| O5 | Predict pump health / near-term failure | Health state (Healthy/Warning/Critical) + failure ETA; degradation flagged before trip |
| O6 | Autonomously self-heal | Isolate untrusted sensor + virtual substitution keeps prediction running with no human action |
| O7 | Safe-stop on genuine critical fault | Dry-run triggers relay pump-stop before damage, autonomously |
| O8 | Immutable audit | Every decision hash-chained; tamper is detectable by the verifier |
| O9 | Enterprise-grade live dashboard | End-to-end sensor→UI latency < 2 s (target < 1 s); responsive; professional UX |
| O10 | Reproducible quantitative evaluation | Results reported on SWaT/WADI with ablations vs. baselines |

---

## 5. Stakeholders

| Stakeholder | Interest | Influence |
|-------------|----------|-----------|
| Project owner / developer (Yeshwanth) | Build, integrate, demo, defend | Decision-maker |
| Academic guide (Ms. Tejashwini A G) | Rigor, novelty, evaluation validity | Approver / examiner |
| Project examiners / reviewers | Technical soundness, live demo, defensibility | Gatekeeper |
| End-user proxy (operator persona) | Clarity, reliability, actionable alerts | Requirements source |
| Future maintainers / co-authors | Clean architecture, documentation | Consumer of handoff |

---

## 6. User Personas

**P1 — Priya, Remote Operations Engineer (primary operator).** Monitors dozens of unmanned stations from a control room. Cannot physically visit quickly. Needs: at-a-glance health, trustworthy alerts (low false-alarm rate), and confidence that the system acted correctly when she wasn't watching. Pain: alert fatigue from systems that cry wolf.

**P2 — Arjun, OT Security Analyst.** Cares about whether a reading can be trusted and whether an incident is attack or fault. Needs: per-sensor trust, attack attribution, and a tamper-proof audit trail for forensics/compliance. Pain: logs that record traffic but not decisions.

**P3 — Devi, System Administrator (dashboard admin).** Manages users, thresholds, device registration, and dashboard configuration. Needs: secure auth, role-based access, configurable thresholds, healthy/observable backend. Pain: brittle admin tooling.

**P4 — Ravi, Reviewer / Examiner (evaluation persona).** Judges novelty, correctness, and the live demo. Needs: a clear cause→effect story on screen, honest framing of proxies/limits, and reproducible numbers. Pain: demos that are smoke and mirrors.

---

## 7. User Stories

Format: *As a [persona], I want [capability], so that [outcome].* Each is traceable to functional requirements (§8) and acceptance criteria (§21).

- **US-01** (P1) As an operator, I want live pump health and per-sensor status on one screen, so that I can assess a remote station in seconds. → FR-D1, FR-D2
- **US-02** (P1) As an operator, I want to be alerted the moment a sensor becomes untrustworthy, so that I know the reading I'm seeing may be compromised. → FR-T3, FR-D4
- **US-03** (P1) As an operator, I want the system to keep predicting health even after a sensor is isolated, so that I don't lose visibility during an incident. → FR-H2
- **US-04** (P2) As a security analyst, I want each anomaly labelled fault-vs-attack with the reason, so that I choose the correct response. → FR-A2, FR-T2
- **US-05** (P2) As a security analyst, I want an immutable, verifiable log of every decision, so that I can run forensics and prove compliance. → FR-L1, FR-L2
- **US-06** (P1) As an operator, I want the pump to stop itself safely before a dry-run destroys it, so that unmanned operation is safe. → FR-R2, FR-H3
- **US-07** (P3) As an admin, I want role-based login and configurable thresholds, so that only authorized staff change safety-critical settings. → FR-S1, FR-D6
- **US-08** (P3) As an admin, I want to see backend/device health (uptime, MQTT connectivity, latency), so that I can trust the monitoring itself. → FR-D5
- **US-09** (P4) As a reviewer, I want to inject a fault or attack from the UI and watch the pipeline respond live, so that I can verify the system is real. → FR-A4, FR-D7
- **US-10** (P1) As an operator, I want the dashboard to update within ~1 second of a physical event, so that what I see reflects reality. → NFR-P1

---

## 8. Functional Requirements

IDs are grouped by subsystem. **MoSCoW** priority in Appendix C.

### Acquisition (FR-Q)
- **FR-Q1** The edge node shall sample all six sensor channels at a configurable rate (default 1 Hz, range 1–10 Hz).
- **FR-Q2** Each reading shall be tagged with sensor ID, timestamp (ISO-8601, ms), and device ID.
- **FR-Q3** Readings shall be published to an MQTT broker on a per-device topic.
- **FR-Q4** The node shall buffer locally and resume publishing after a broker disconnect without data loss for ≥ 60 s.

### Preprocessing (FR-P)
- **FR-P1** The pipeline shall apply noise filtering (median/low-pass), min-max normalization, and missing-value imputation.
- **FR-P2** The pipeline shall assemble sliding time windows (default 30 samples, configurable).

### Anomaly Detection (FR-A)
- **FR-A1** The system shall flag statistical anomalies per window using Isolation Forest trained on clean baseline data.
- **FR-A2** The system shall run cross-sensor correlation/physics checks (e.g., current vs. pressure consistency) to classify an anomaly as **physical fault** or **cyber-attack** (FDI / replay / spoof).
- **FR-A3** The system shall output an anomaly flag + severity + attribution label + reason tag.
- **FR-A4** The system shall accept operator-injected fault/attack scenarios (for demo/testing) via an authenticated control channel.

### Trust Evaluation (FR-T)
- **FR-T1** The system shall maintain a per-sensor trust score T ∈ [0,1] using a Beta-reputation model updated every window.
- **FR-T2** Trust updates shall weight consistency, cross-sensor correlation, and historical reliability.
- **FR-T3** The system shall classify each sensor as Trusted (T ≥ 0.7), Suspicious (0.4 ≤ T < 0.7), or Malicious (T < 0.4).
- **FR-T4** Trust scores shall recover toward baseline when a sensor returns to consistent behaviour.

### Predictive Maintenance (FR-M)
- **FR-M1** The system shall predict pump health state (Healthy / Warning / Critical) from trust-weighted windows using an LSTM.
- **FR-M2** The system shall output a near-term failure prognosis (failure-ETA / cycles-ahead), honestly framed as short-horizon.
- **FR-M3** Low-trust sensor inputs shall be down-weighted before entering the predictive model.

### RL Decision (FR-RL)
- **FR-RL1** The agent shall consume a state vector `[health, anomaly_flag, T1..T6, failure_ETA]`.
- **FR-RL2** The agent shall select from: Continue · Reduce Weight · Isolate Sensor · Trigger Alert · **Safe Pump-Stop**.
- **FR-RL3** The agent's reward shall penalize false isolation, missed critical faults, and downtime.
- **FR-RL4** The agent shall be replaceable by a deterministic rule-based fallback if the trained policy is unavailable (fail-safe).

### Self-Healing (FR-H)
- **FR-H1** On isolation, the system shall drop/down-weight the offending sensor from fusion.
- **FR-H2** The system shall reconstruct an isolated sensor's value via LSTM digital-twin **virtual substitution**, with an attached uncertainty estimate.
- **FR-H3** Substitution shall be **bounded**: time-limited, uncertainty-capped, and if real-vs-twin divergence exceeds a threshold the system shall escalate to Safe Pump-Stop.
- **FR-H4** Healing shall require no human action and shall complete within one processing cycle of the decision.

### Actuation / Safety (FR-R)
- **FR-R1** The relay shall be driveable to stop the pump on command.
- **FR-R2** A dry-run (source-reservoir empty) shall trigger autonomous Safe Pump-Stop before pump damage.
- **FR-R3** A hardware/software watchdog shall default the pump to a safe state on edge-node failure.

### Ledger / Audit (FR-L)
- **FR-L1** Every trust drop, anomaly, RL action, and heal shall be written as a hash-chained block (event + timestamp + prev-hash).
- **FR-L2** A verifier shall detect any tampering of a prior block.
- **FR-L3** Ledger entries shall be queryable/exportable from the dashboard.

### Dashboard (FR-D)
- **FR-D1** The dashboard shall render live per-sensor time-series (last 60 s) updating in real time.
- **FR-D2** The dashboard shall show a color-coded per-sensor trust panel and a machine-health badge.
- **FR-D3** The dashboard shall show failure-ETA, the RL action log, and the ledger event stream.
- **FR-D4** The dashboard shall surface active alerts with severity and reason.
- **FR-D5** The dashboard shall show system/observability health (MQTT connectivity, sample rate, end-to-end latency).
- **FR-D6** The dashboard shall allow authorized admins to configure thresholds and register devices.
- **FR-D7** The dashboard shall provide an authenticated "inject scenario" control for live demos.
- **FR-D8** The dashboard shall visibly mark any channel currently served by virtual substitution.

---

## 9. Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-P1 | Performance | End-to-end latency, sensor event → dashboard render | < 2 s (target < 1 s) |
| NFR-P2 | Performance | Full sense→decide→act cycle at the edge | < 2 s |
| NFR-P3 | Performance | Self-healing reconfiguration after isolation decision | < 500 ms |
| NFR-R1 | Reliability | Continuous operation through single-sensor loss | No pipeline crash; prediction continues |
| NFR-R2 | Reliability | Broker reconnection / buffered resume | ≤ 60 s data retained |
| NFR-S1 | Security | Dashboard auth + role-based access | Enforced on all admin/control endpoints |
| NFR-S2 | Security | Ledger integrity | 100% tamper-detectable |
| NFR-SC1 | Scalability | Logical device model | Support N devices without redesign (demo: 1) |
| NFR-U1 | Usability | Operator can assess station status | ≤ 5 s glance |
| NFR-U2 | Usability | Responsive UI (desktop primary, tablet graceful) | No layout break ≥ 768 px |
| NFR-M1 | Maintainability | Modular subsystems, independently testable | Each module has a defined I/O contract |
| NFR-O1 | Observability | Structured logs + health metrics | Backend + edge |
| NFR-A1 | Availability | Demo-session uptime | ≥ 99% during a 30-min demo |

---

## 10. System Architecture

### 10.1 Layered overview
```
[ PUMP + 6 SENSORS ]            Physical layer (bench rig)
        |  GPIO / I2C / SPI (ADC)
        v
[ Raspberry Pi 4 EDGE NODE ]    Acquisition + edge inference
   - sensor drivers   - preprocessing
   - anomaly + trust + LSTM   - RL agent   - self-heal orchestrator
   - relay driver (actuation)   - MQTT publisher
        |  MQTT (telemetry, events, decisions, ledger)
        v
[ MQTT BROKER ]  (Mosquitto)
        |
        v
[ BACKEND SERVICE ]  (FastAPI / Node)
   - MQTT subscriber   - WebSocket gateway
   - REST API (auth, config, history, ledger)
   - time-series store   - ledger store
        |  WebSocket (live)  +  REST (history/config)
        v
[ ADMIN WEB DASHBOARD ]  (React SPA)
```

### 10.2 Compute placement
Inference (anomaly, trust, LSTM, RL, healing, actuation) runs **at the edge** to satisfy the < 500 ms healing budget and to reflect the real "no cloud round-trip for safety decisions" constraint. The backend and dashboard are for **visualization, history, configuration, and audit** — never in the safety-critical path. This separation is itself a defensible design point.

### 10.3 Key data contracts
- **Telemetry message** (edge→broker, 1 Hz): `{device_id, ts, sensors:{temp,vib,pressure,humidity,gas,current}, sample_seq}`
- **Decision message** (edge→broker, event-driven): `{device_id, ts, anomaly:{flag,severity,attribution,reason}, trust:{s1..s6}, health, failure_eta, rl_action, healing:{isolated[], substituted[]}}`
- **Ledger message** (edge→broker, event-driven): `{device_id, ts, block_index, event, payload_hash, prev_hash, this_hash}`

Full DFD notes in **Appendix F**.

---

## 11. Features Breakdown

| Feature | Description | Primary FRs | Priority |
|---------|-------------|-------------|----------|
| F1 · Live telemetry ingest | Six-channel 1 Hz acquisition + publish | FR-Q1–4 | Must |
| F2 · Preprocessing pipeline | Filter, normalize, window | FR-P1–2 | Must |
| F3 · Anomaly detection + attribution | Isolation Forest + physics checks; fault vs attack | FR-A1–3 | Must |
| F4 · Dynamic trust engine | Beta-reputation per-sensor scoring | FR-T1–4 | Must |
| F5 · Trust-filtered prognosis | LSTM health + failure-ETA on trust-weighted data | FR-M1–3 | Must |
| F6 · RL decision agent | Contextual response selection + rule fallback | FR-RL1–4 | Must |
| F7 · Self-healing + virtual substitution | Isolate + reconstruct, bounded by uncertainty | FR-H1–4 | Must |
| F8 · Safe actuation | Relay stop; dry-run auto-stop; watchdog | FR-R1–3 | Must |
| F9 · Tamper-evident ledger | Hash-chain + verifier + export | FR-L1–3 | Should |
| F10 · Real-time dashboard | Live charts, trust, health, actions, ledger | FR-D1–5, D8 | Must |
| F11 · Admin & config | Auth, RBAC, thresholds, device registration | FR-D6, FR-S | Should |
| F12 · Demo scenario injection | Authenticated fault/attack triggers | FR-A4, FR-D7 | Must |

---

## 12. Data Requirements & Telemetry

### 12.1 Sensor channels (logical → physical, with honest proxy notes)
| Ch | Logical signal | Bench part | Interface | Real-world analogue | Proxy note |
|----|----------------|-----------|-----------|--------------------|-----------|
| 1 | Temperature | DS18B20 | 1-Wire | Motor/bearing temp | Direct |
| 2 | Vibration | ADXL335 | Analog→ADC | Bearing/cavitation/impeller | Direct |
| 3 | Pressure | BMP180 | I2C | Discharge/line pressure | **Proxy** — reads atmosphere, not water-line |
| 4 | Humidity | DHT22 | Digital | Seal-leak / wet-well moisture | Indicative |
| 5 | Gas | MQ-135 | Analog→ADC | Wet-well air quality | **Proxy** — VOC/CO2, not H2S |
| 6 | Current | INA219 | I2C | Motor load / dry-run | Direct (replaces ACS712 — see BOM) |

> **Design integrity note.** Temperature (DS18B20) is kept independent of humidity (DHT22) so the cross-sensor correlation term in the trust engine is not silently defeated by two perfectly-correlated channels from one part. Current sensing uses INA219 (not ACS712) because a small pump's sub-1 A draw is unresolvable in ACS712 noise. These are stated openly in the paper and demo.

### 12.2 Sampling, retention, volume
- Rate: 1 Hz default (6 channels) → ~518k samples/device/day.
- Retention: rolling 24 h high-res on backend; full session archived for evaluation.
- Windowing: 30-sample sliding window (30 s at 1 Hz).

### 12.3 Datasets (evaluation)
- **Primary quantitative:** SWaT / WADI (iTrust) — labelled physical attacks on water treatment/distribution.
- **Corroborating (optional):** Tennessee Eastman Process — pre-built faults + published attack variants.
- **Bench:** self-collected pump-rig runs with scripted fault/attack injections (labelled).

### 12.4 Attack/fault injection taxonomy (for test data)
Faults: gradual drift · sudden spike · stuck-at · dry-run (physical). Attacks: bias FDI · ramp FDI · replay · constant-value spoof. Each injectable per-channel with magnitude bounds and a stealth constraint for advanced tests.

---

## 13. Literature Survey Insights

- **Predictive maintenance (LSTM/RF):** high accuracy on clean data but assumes trustworthy sensors — no adversarial robustness. *Gap SHTAPM fills: trust-filtering.*
- **Anomaly detection (Isolation Forest, LSTM-AE):** effective but high false positives under drift and no fault-vs-attack disambiguation. *Gap: attribution.*
- **Trust management (Beta-reputation, Bao & Chen):** mostly static, rule-based, no learning-based response. *Gap: RL-coupled dynamic trust.*
- **RL for security/control:** strong at adaptive response but rarely tied to predictive maintenance, and largely for control not prognosis. *Gap: RL over trust+prognosis state.*
- **Blockchain in IIoT:** typically logs network traffic, not high-level autonomous decisions. *Gap: decision-level provenance.*
- **Wind/water PdM-under-attack:** an emerging thin niche; "self-healing" and "trust-aware" are essentially unclaimed in this combination. *Positioning: open ground.*

The synthesis: no prior work unifies **disambiguation + dynamic trust + trust-filtered prognosis + autonomous self-healing + decision-level audit** for remote water infrastructure. That unification, demonstrated live and validated on SWaT/WADI, is the contribution.

---

## 14. Competitive / Existing Solution Analysis

| Solution class | Does PdM | Detects attacks | Fault-vs-attack | Dynamic trust | Autonomous self-heal | Decision audit |
|----------------|:---:|:---:|:---:|:---:|:---:|:---:|
| Commercial CMS (vibration/SCADA) | Yes | No | No | No | No | Partial |
| ICS IDS (network anomaly) | No | Yes | No | No | No | Traffic logs |
| Static trust frameworks | No | Partial | No | Static | No | No |
| RL resilient-control research | No | Yes | Partial | No | Control-only | No |
| **SHTAPM** | Yes | Yes | Yes | **Dynamic** | Yes | **Decision-level** |

The competitive white space is the full row — no incumbent occupies it, particularly the combination of disambiguation and *keep-running* self-healing.

---

## 15. Assumptions

- A1 — The bench pump rig is an accepted scale proxy for a remote pumping station; proxy sensors are labelled honestly.
- A2 — A single edge node (Raspberry Pi 4) has sufficient compute for the models at demo scale (verified in Phase 0 spike).
- A3 — Wi-Fi/LAN connectivity is available between edge, broker, backend, and dashboard during the demo.
- A4 — SWaT/WADI access is obtainable for quantitative evaluation; if not, TEP + bench data substitute.
- A5 — The LSTM twin, trained on clean pump data, can reconstruct an isolated channel with usable short-horizon accuracy.
- A6 — Demo audience interacts via the dashboard, not the CLI.
- A7 — Power and water are available and safe to operate at the demo venue.

---

## 16. Constraints

- C1 — Hardware budget ≤ ~₹10,000 (BOM, Appendix D).
- C2 — Student timeline; models must be trainable on a laptop/Colab GPU.
- C3 — Zero-cost software stack (open-source only).
- C4 — Safety-critical actuation is limited to **safe-stop**; the system must not autonomously drive the pump into unsafe operation (functional-safety scoping).
- C5 — Bench electrical work limited to low-voltage DC; mains isolation via relay/adapter only.
- C6 — Real water-line pressure and true wet-well gas are not measured (proxy constraint), and must not be over-claimed.
- C7 — Demo network may be unreliable venue Wi-Fi; system must degrade gracefully to local/simulation mode.

---

## 17. Risks & Mitigation

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|:---:|:---:|-----------|
| R1 | Live hardware fails during demo | Med | High | Identical demo runs on recorded/sim data via same dashboard (fallback mode); dry-run test rehearsed |
| R2 | Venue Wi-Fi drops | Med | High | Edge buffers; broker+backend runnable on localhost; offline demo profile |
| R3 | Virtual substitution is circular / gameable | Med | High | Bounded, uncertainty-capped substitution; divergence→safe-stop; test SH-SAD cases explicitly |
| R4 | Reviewer: "attacks never happened on water sensors" | Med | Med | Cite Oldsmar + SWaT/WADI; frame FDI as documented-adjacent + benchmarked |
| R5 | ACS712 can't read pump current | High (pre-empted) | High | Replaced with INA219 in BOM |
| R6 | Temp/humidity from one part break trust correlation | High (pre-empted) | Med | Split to DS18B20 + DHT22 |
| R7 | Latency budget missed | Med | Med | Edge inference; lightweight models; WebSocket not polling; measured in E2E tests |
| R8 | RL policy unstable/untrained by demo | Med | High | Deterministic rule-based fallback (FR-RL4) validated first |
| R9 | Water + electronics hazard | Low | High | Splash guards, sealed junctions, low-voltage DC, GFCI adapter |
| R10 | Overfitting claims on tiny bench data | Med | Med | Primary numbers from SWaT/WADI; bench = qualitative demo only |

---

## 18. Hardware Demo & Setup Guide
*(Custom section — live demonstration is a graded deliverable.)*

### 18.1 Physical assembly assumptions
- Two reservoirs (source + destination); 12 V DC pump moves water source→destination via silicone tubing; return path optional for a closed loop.
- Raspberry Pi 4 is the edge node; sensors wired per §12.1. Analog sensors (ADXL335, MQ-135) go through an **MCP3008 ADC** on SPI; BMP180 + INA219 on I2C; DS18B20 on 1-Wire; DHT22 on a digital GPIO.
- INA219 is wired **in series** with the pump's 12 V supply (high-side) to read load current.
- Relay module on a GPIO switches pump power (low-voltage side); buzzer + status LEDs on GPIO.
- All water-adjacent wiring uses sealed junctions and a splash guard; mains adapter behind a GFCI.

### 18.2 Environmental prep (venue checklist)
- Level, water-safe surface; towels + spill tray; drain/empty bucket accessible.
- Reservoirs pre-filled to marked lines; a labelled "attack" and "dry-run" prompt card.
- Pi on stable power (not the pump supply); network: local broker/backend on the Pi or a laptop so the demo does **not** depend on venue Wi-Fi.
- Dashboard laptop charged; second screen/projector mirrored; font sizes bumped for the room.
- **Rehearse the dry-run stop at least twice** before the audience arrives; confirm the relay clicks off before the pump runs dry.

### 18.3 Pre-flight checklist (T-15 min)
1. Power Pi → confirm all six channels streaming (dashboard health panel all green).
2. Confirm MQTT connected, sample rate = 1 Hz, E2E latency < 1 s on the health panel.
3. Confirm relay control (manual test stop → start).
4. Confirm ledger verifier passes on a fresh chain.
5. Load the "clean baseline" so trust scores sit at green.
6. Arm fallback: recorded-session profile one click away.

### 18.4 Presentation script / flow (the "wow" sequence)
> Target run time: 6–8 minutes. Narrate cause→effect; let the screen prove each claim.

1. **Set the scene (30 s).** "This is a remote, unmanned pumping station. No one can get to it quickly. Watch what happens when a sensor lies, and when the pump actually fails." Show the dashboard: pump running, six green trust bars, health = Healthy, failure-ETA counting.
2. **Inject the attack (45 s).** From the dashboard, spoof the **pressure** channel to a constant, plausible value. The pump keeps running perfectly. → *Audience sees the raw chart flatten while the machine is visibly fine.*
3. **Detect + attribute (45 s).** Within ≤ 3 windows the pressure trust bar drops to red; the alert reads **"Attack — physics violation (pressure inconsistent with current)."** Buzzer + red LED fire. → *This is the disambiguation moment — say it out loud: "not a fault — a lie."*
4. **Self-heal (60 s).** The RL agent isolates the pressure sensor; the channel is marked **VIRTUAL**; the LSTM twin reconstructs its value; health prediction never drops out. The pump keeps running. → *"No human touched anything. It healed itself."*
5. **The physical fault (60 s).** Empty the source reservoir (or open the labelled valve). Current and pressure collapse; the agent issues **Safe Pump-Stop**; the relay clicks the pump off **before** dry-run damage. → *"This time it's real — and it stops itself, safely."*
6. **Prove it (45 s).** Open the ledger view: every step is a valid hash-chained block. Tamper one block live → verifier flashes red. → *"Everything it decided is provable, and you can't rewrite history."*
7. **Close (30 s).** Recap: detected, told fault from attack, healed autonomously, stopped safely, logged immutably — the whole SHTAPM loop, live.
8. **Fallback (if hardware misbehaves).** Switch to recorded-session profile; identical narrative, same dashboard. *The demo never dies on stage.*

### 18.5 Teardown
Power pump off → drain reservoirs → power Pi down cleanly (avoid SD corruption) → export the session ledger + telemetry for the report.

---

## 19. Testing Strategy Overview

**Philosophy.** Every component is tested at three levels of adversity — **Happy** (expected input), **Edge** (boundary/stress), **Sad** (failure/malicious) — and the system is validated **end-to-end from a physical sensor event to a rendered pixel on the dashboard**. Nothing is "done" until its E2E path is green.

**Test layers.**
- **Unit** — per module (drivers, filters, trust update, ledger hash, API handlers).
- **Integration** — module pairs (edge→broker, broker→backend, backend→WS→UI).
- **E2E** — physical/simulated sensor event → pipeline → dashboard render, with latency asserted.
- **Non-functional** — latency, reliability under disconnect, security/authz, tamper-detection.
- **Demo rehearsal** — the §18.4 script executed as an acceptance gate.

**Tooling (suggested).** pytest (backend/edge Python), Jest + React Testing Library (frontend), Playwright/Cypress (E2E UI), MQTT test client + recorded bagfiles/CSV for deterministic replay, k6/Locust for load, a small latency-probe harness that timestamps a synthetic sensor event and the corresponding DOM update.

**Definitions.**
- *Happy* = valid, in-range, authorized input under normal conditions.
- *Edge* = boundary values, timing races, resource limits, reconnects, partial data.
- *Sad* = invalid/malicious input, component failure, attack, unauthorized access.

**Exit criteria.** All Must-priority features pass Happy+Edge+Sad; E2E latency < 2 s; safe-stop verified physically; ledger tamper-detection verified; demo script rehearsed twice end-to-end.

---

## 20. Phase-Wise Implementation with Exhaustive Test Cases

> Each phase lists **Scope → Tasks → Deliverables → Test Cases (Happy / Edge / Sad)**. Test IDs are `P{phase}-{feature}-{H|E|S}{n}`.

---

### Phase 0 — Foundations & Spikes
**Scope.** De-risk the two biggest unknowns before committing: edge compute headroom and the latency path.
**Tasks.**
- Flash Pi OS; set up Python env; confirm I2C/SPI/1-Wire enabled.
- Spike: read one sensor of each interface type; confirm INA219 resolves pump current.
- Spike: publish MQTT → subscribe in backend → push over WebSocket → render a number in a bare React page; **measure end-to-end latency**.
- Spike: time an LSTM forward pass + Isolation Forest score on the Pi.
**Deliverables.** Go/no-go on architecture; measured baseline latency; confirmed compute budget.

**Test cases**

| ID | Type | Case | Expected |
|----|------|------|----------|
| P0-SPIKE-H1 | Happy | Each interface reads its sensor | Valid values within datasheet range |
| P0-SPIKE-H2 | Happy | Sensor→UI number render | Value appears, latency logged |
| P0-SPIKE-E1 | Edge | INA219 at pump idle vs load | Distinguishable current delta above noise |
| P0-SPIKE-E2 | Edge | LSTM+IF timing under load | Total edge inference < 500 ms |
| P0-SPIKE-S1 | Sad | Disconnect a sensor mid-read | Driver raises handled error, no crash |
| P0-SPIKE-S2 | Sad | Broker down during publish | Publisher retries/buffers, no data loss |

---

### Phase 1 — Hardware Prototyping & Acquisition
**Scope.** Full six-channel rig + reliable acquisition (F1).
**Tasks.**
- Assemble rig (§18.1); wire all six channels; INA219 in series; relay + buzzer + LEDs.
- Implement sensor drivers with per-channel calibration + range clamping.
- Implement 1 Hz sampler with ISO-8601 timestamps + sensor/device IDs.
- Implement local buffer + MQTT publisher (FR-Q1–4).
- Implement relay driver + hardware watchdog (FR-R1, FR-R3).
**Deliverables.** Streaming six-channel telemetry; manual relay stop; buffered publish.

**Test cases**

| ID | Type | Case | Expected |
|----|------|------|----------|
| P1-ACQ-H1 | Happy | 10-min run, all channels | < 1% dropped samples; all fields present |
| P1-ACQ-H2 | Happy | Timestamp + ID tagging | Every message well-formed, monotonic seq |
| P1-ACQ-E1 | Edge | Max rate 10 Hz | Stable, no buffer overflow |
| P1-ACQ-E2 | Edge | Sensor at range boundary (e.g., temp max) | Clamped/flagged, not garbage |
| P1-ACQ-E3 | Edge | Broker drop for 30 s then restore | Buffered, replayed in order, no loss |
| P1-ACQ-S1 | Sad | Unplug DS18B20 mid-run | Channel flagged missing; others continue |
| P1-ACQ-S2 | Sad | Corrupt I2C (loose SDA) | Handled error + reconnect; no crash |
| P1-RELAY-H1 | Happy | Command stop/start | Pump toggles; state reflected |
| P1-RELAY-S1 | Sad | Edge process killed | Watchdog defaults pump to safe (off) |

---

### Phase 2 — Edge Intelligence: Preprocessing, Anomaly, Trust
**Scope.** F2, F3, F4 on the edge.
**Tasks.**
- Preprocessing: median/low-pass filter, min-max normalize, 30-sample windows (FR-P1–2).
- Train Isolation Forest on clean baseline; implement scoring (FR-A1).
- Implement cross-sensor physics/correlation checks + attribution logic (FR-A2–3).
- Implement Beta-reputation trust update + classification + recovery (FR-T1–4).
- Implement authenticated scenario-injection hook (FR-A4).
**Deliverables.** Per-window anomaly flag + attribution + reason; per-sensor trust scores.

**Test cases**

| ID | Type | Case | Expected |
|----|------|------|----------|
| P2-PRE-H1 | Happy | Clean stream | Windows well-formed, normalized [0,1] |
| P2-PRE-E1 | Edge | Missing value in window | Imputed; window still valid |
| P2-PRE-S1 | Sad | All-NaN window | Rejected safely; logged; no propagation |
| P2-ANOM-H1 | Happy | Clean data | No false anomaly over 5-min baseline |
| P2-ANOM-H2 | Happy | Injected spike fault | Flagged ≤ 3 windows, attribution = fault |
| P2-ANOM-H3 | Happy | Injected constant-spoof attack | Flagged ≤ 3 windows, attribution = attack |
| P2-ANOM-E1 | Edge | Slow drift near threshold | Eventually flagged; no oscillation |
| P2-ANOM-E2 | Edge | Simultaneous fault + attack on different channels | Both flagged, attributed independently |
| P2-ANOM-S1 | Sad | Adaptive stealth FDI (stays under naive residual) | Trust/correlation still degrades; caught or flagged suspicious |
| P2-TRUST-H1 | Happy | Healthy sensor | Trust stays ≥ 0.7 |
| P2-TRUST-H2 | Happy | Spoofed sensor | Trust < 0.4 within ≤ 3 windows |
| P2-TRUST-E1 | Edge | Sensor recovers after transient | Trust climbs back toward baseline |
| P2-TRUST-E2 | Edge | Two correlated channels both drift | Correlation term doesn't falsely exonerate |
| P2-TRUST-S1 | Sad | Collusive attack on 2 channels to fake correlation | Historical-reliability term prevents full trust |

---

### Phase 3 — Prognosis, RL Decision, Self-Healing
**Scope.** F5, F6, F7, F8 (safety) on the edge.
**Tasks.**
- Train LSTM health/failure-ETA on trust-weighted windows (FR-M1–3).
- Implement RL agent (DQN) over the state vector + reward; implement deterministic fallback (FR-RL1–4).
- Implement self-healing: isolation/re-weighting + **bounded, uncertainty-aware** virtual substitution + divergence→safe-stop (FR-H1–4).
- Implement dry-run detection → autonomous Safe Pump-Stop (FR-R2).
**Deliverables.** Health + ETA; autonomous action selection; self-heal keeps prediction alive; safe-stop works physically.

**Test cases**

| ID | Type | Case | Expected |
|----|------|------|----------|
| P3-PRED-H1 | Happy | Degrading pattern | Health → Warning/Critical before failure; ETA decreases |
| P3-PRED-E1 | Edge | One channel isolated | Prediction continues on remaining + substitute |
| P3-PRED-S1 | Sad | Two channels lost | Prediction continues or gracefully degrades with flagged uncertainty |
| P3-RL-H1 | Happy | Suspicious sensor state | Agent chooses Reduce-Weight/Isolate appropriately |
| P3-RL-H2 | Happy | Critical health + dry-run | Agent chooses Safe Pump-Stop |
| P3-RL-E1 | Edge | Borderline trust (0.4/0.7 exact) | Deterministic, non-oscillating decision |
| P3-RL-S1 | Sad | Trained policy file missing | Rule-based fallback engages; safety preserved |
| P3-RL-S2 | Sad | Reward-gaming input (attacker nudges to force false-isolate) | False-isolation penalty resists; no needless shutdown |
| P3-HEAL-H1 | Happy | Isolate spoofed sensor | Virtual substitution active; channel marked VIRTUAL; prediction continuous |
| P3-HEAL-E1 | Edge | Substitution near uncertainty cap | Confidence flagged high; alert raised |
| P3-HEAL-S1 | Sad | Real state diverges from twin beyond threshold | Escalates to Safe Pump-Stop (no limping on fantasy) |
| P3-HEAL-S2 | Sad | Attacker controls isolated channel's substitute expectation | Bounded window + divergence check prevents indefinite trust |
| P3-SAFE-H1 | Happy | Empty source reservoir | Relay stops pump before dry-run damage |
| P3-SAFE-S1 | Sad | Dry-run + spoofed "healthy" pressure | Current-based cross-check still triggers stop |

---

### Phase 4 — Backend, MQTT→WebSocket, Ledger
**Scope.** Broker, backend service, real-time gateway, ledger store, REST API (F9 + plumbing for F10).
**Tasks.**
- Stand up Mosquitto; define topics; secure with credentials (Appendix E).
- Backend: MQTT subscriber → time-series store; WebSocket gateway for live push; REST for history/config/auth/ledger.
- Implement ledger: hash-chain writer + verifier + export (FR-L1–3).
- Implement auth + RBAC + config endpoints (FR-S1, FR-D6).
**Deliverables.** Live data reaches a WebSocket client; history/query API; verifiable ledger.

**Test cases**

| ID | Type | Case | Expected |
|----|------|------|----------|
| P4-WS-H1 | Happy | Client subscribes | Receives live telemetry + decisions in order |
| P4-WS-E1 | Edge | 5 concurrent clients | All receive; no lag > target |
| P4-WS-E2 | Edge | Client reconnect | Resumes cleanly; no dup storm |
| P4-WS-S1 | Sad | Malformed MQTT payload | Rejected/logged; gateway stays up |
| P4-LED-H1 | Happy | Append events | Valid chain; each block links prev-hash |
| P4-LED-H2 | Happy | Verify intact chain | Verifier passes |
| P4-LED-S1 | Sad | Tamper a middle block | Verifier fails, pinpoints break |
| P4-LED-S2 | Sad | Reorder/replay blocks | Detected as invalid |
| P4-API-H1 | Happy | Query last-hour history | Correct series returned |
| P4-API-E1 | Edge | Empty range query | Empty set, 200, no error |
| P4-AUTH-S1 | Sad | Unauthed config write | 401/403; no state change |
| P4-AUTH-S2 | Sad | Operator tries admin action (RBAC) | Forbidden; audited |

---

### Phase 5 — Admin Dashboard (Frontend)
**Scope.** Enterprise-grade real-time SPA (F10, F11, F12).
**Tasks.**
- React SPA; design system (consistent tokens, spacing, typography — professional, not templated).
- Live per-sensor charts (last 60 s), trust panel (green/yellow/red), health badge, failure-ETA meter (FR-D1–3).
- Alerts panel with severity + reason; RL action log; ledger event stream (FR-D3–4).
- System/observability panel: MQTT status, sample rate, **live E2E latency** (FR-D5).
- VIRTUAL-channel indicator (FR-D8); auth screens + RBAC-gated admin/config (FR-D6); authenticated scenario-injection controls (FR-D7).
- Responsive layout (desktop primary, tablet graceful); loading/empty/error states everywhere.
**Deliverables.** A dashboard that looks and behaves like a top-tier product, updating live.

**Test cases**

| ID | Type | Case | Expected |
|----|------|------|----------|
| P5-UI-H1 | Happy | Live stream connected | Charts animate smoothly at 1 Hz; no jank |
| P5-UI-H2 | Happy | Trust drop event | Bar turns red; alert appears with reason |
| P5-UI-H3 | Happy | Virtual substitution active | Channel badged VIRTUAL clearly |
| P5-UI-E1 | Edge | 60-min continuous session | No memory leak; chart windowing stable |
| P5-UI-E2 | Edge | Tablet width (768px) | Layout reflows, nothing clipped |
| P5-UI-E3 | Edge | Burst of 50 events | List virtualizes; UI stays responsive |
| P5-UI-S1 | Sad | WebSocket drops | Clear "reconnecting" state; auto-resume; no blank screen |
| P5-UI-S2 | Sad | Backend 500 on history | Error state, retry affordance; live panel unaffected |
| P5-UI-S3 | Sad | Unauthorized user opens admin route | Redirected/blocked |
| P5-INJ-H1 | Happy | Inject attack from UI | Round-trips to edge; pipeline reacts on screen |
| P5-INJ-S1 | Sad | Unauthed inject attempt | Blocked; audited |

---

### Phase 6 — End-to-End Integration & Demo Hardening
**Scope.** The whole chain, physical sensor → rendered pixel, plus demo resilience.
**Tasks.**
- Wire all phases together on the real rig; run the full §18.4 script.
- Implement the recorded-session **fallback profile** (R1/R2) behind a toggle.
- Latency-probe harness: timestamp a synthetic physical event → assert DOM update < 2 s.
- Rehearse dry-run safe-stop physically; rehearse tamper-detection live.
- Harden: reconnection, watchdog, graceful sim-mode, error surfaces.
**Deliverables.** A demo-ready, resilient, measured end-to-end system.

**Test cases (E2E — hardware to UI)**

| ID | Type | Case | Expected |
|----|------|------|----------|
| P6-E2E-H1 | Happy | Physical vibration change | Dashboard chart reflects it < 2 s; health updates |
| P6-E2E-H2 | Happy | UI-injected pressure spoof → heal | Trust red → isolate → VIRTUAL → prediction continuous, all visible |
| P6-E2E-H3 | Happy | Empty reservoir → safe-stop | Pump physically stops; UI shows Safe Pump-Stop + ledger block |
| P6-E2E-H4 | Happy | Tamper ledger live | Verifier flips red on screen |
| P6-E2E-E1 | Edge | Venue Wi-Fi drop mid-demo | Edge buffers; UI shows reconnecting; recovers with no loss |
| P6-E2E-E2 | Edge | Latency under full load (all panels live) | Still < 2 s end-to-end |
| P6-E2E-E3 | Edge | Rapid attack→heal→fault sequence | Each stage renders in correct order, no race |
| P6-E2E-S1 | Sad | Pump hardware dead on demo day | Fallback profile runs identical narrative |
| P6-E2E-S2 | Sad | Sensor unplugged mid-demo | Channel flagged; system self-heals; demo continues |
| P6-E2E-S3 | Sad | Broker killed mid-demo | Backend + UI show degraded state; recover on restart; no crash |

---

### Phase 7 — Quantitative Evaluation (Paper-grade)
**Scope.** Defensible numbers for the report/paper (not demo).
**Tasks.**
- Run pipeline on SWaT/WADI (and/or TEP) with the injection taxonomy (§12.4).
- Ablations: PdM-only vs +anomaly vs +static-trust vs +dynamic-trust(full); report deltas.
- Metrics: RUL/health accuracy under attack vs clean; **fault-vs-attack confusion matrix**; detection/isolation latency; false-isolation rate; uptime vs % sensors compromised (a curve, not a point).
- Adaptive/white-box adversary test (attacker aware of the trust mechanism).
**Deliverables.** Results tables + figures; honest threat model; reproducible scripts.

**Test cases**

| ID | Type | Case | Expected |
|----|------|------|----------|
| P7-EVAL-H1 | Happy | Full model on labelled attacks | Attribution ≥ target; metrics reported |
| P7-EVAL-E1 | Edge | Increasing % compromise | Graceful degradation curve, not a cliff |
| P7-EVAL-S1 | Sad | Adaptive adversary gaming trust | Robustness quantified; limits reported honestly |

---

## 21. Acceptance Criteria

The system is accepted when **all** hold:
- **AC1** All six channels stream live to the dashboard with < 1% loss over 10 min (O1, F1).
- **AC2** An injected attack is detected, attributed as *attack*, and the offending sensor's trust drops < 0.4 within ≤ 3 windows (O2–O4).
- **AC3** After isolation, virtual substitution keeps health prediction running with the channel visibly marked VIRTUAL (O6, F7, FR-D8).
- **AC4** A physical dry-run triggers autonomous Safe Pump-Stop before damage (O7, FR-R2).
- **AC5** Every decision is hash-chained and a live tamper is caught by the verifier (O8, F9).
- **AC6** End-to-end sensor→UI latency < 2 s under full load (O9, NFR-P1).
- **AC7** Admin/control endpoints enforce auth + RBAC; unauthorized actions are blocked and audited (NFR-S1).
- **AC8** The §18.4 demo script runs start-to-finish twice, including the fallback profile (R1).
- **AC9** Quantitative results on SWaT/WADI (or documented substitute) with ablations and a confusion matrix are produced (O10).
- **AC10** Every Must feature passes its Happy + Edge + Sad test cases.

---

## 22. Future Enhancements

- Multi-device fleet view (N stations) with map + rollup health.
- Uncertainty-quantified twin (Bayesian/ensemble) for principled substitution bounds.
- Federated trust across stations (shared reputation without shared raw data).
- Real permissioned ledger (Hyperledger) with multi-operator consensus — justified only where multiple distrusting parties exist.
- Edge model updates / OTA with signed artifacts.
- Physics-informed digital twin for higher-fidelity substitution.
- Alert routing (SMS/email/Slack) and on-call escalation.
- Anomaly explainability (per-decision feature attributions) in the UI.

---

## 23. Developer Handoff Summary (One-Pager)

**What you're building.** A cyber-physical monitoring + self-healing system for a bench water-pump proxy of a remote pumping station, with an enterprise-grade live dashboard.

**Stack (suggested).** Edge: Python on Raspberry Pi 4 (sensor drivers, scikit-learn Isolation Forest, PyTorch/TF LSTM, Stable-Baselines3 DQN, hash-chain, MQTT publisher, relay/watchdog). Transport: Mosquitto MQTT. Backend: FastAPI or Node (MQTT subscriber, WebSocket gateway, REST, time-series + ledger store, auth/RBAC). Frontend: React SPA (charts via Recharts/Chart.js, WebSocket client, design system).

**The one loop that matters.** `sense → preprocess → (anomaly + trust + LSTM) → RL decide → self-heal (isolate + virtual-substitute, bounded) → actuate/safe-stop → log → visualize`. Inference lives at the **edge**; backend/UI are visualization + audit only.

**Non-negotiables.** < 500 ms self-heal; < 2 s sensor→UI; autonomous safe-stop; tamper-evident ledger; RL has a rule-based fallback; substitution is bounded and escalates to safe-stop on divergence; auth+RBAC on all control/admin.

**Build order.** P0 spikes → P1 hardware/acquire → P2 anomaly+trust → P3 prognosis+RL+heal+safety → P4 backend+ledger → P5 dashboard → P6 E2E+demo hardening → P7 evaluation.

**Definition of done.** All §21 acceptance criteria green; every Must feature passes Happy/Edge/Sad; demo script rehearsed twice incl. fallback.

**Honesty guardrails (defensibility).** Pressure/gas are labelled proxies; INA219 (not ACS712); temp/humidity split; bench = qualitative, SWaT/WADI = quantitative; FDI framed as documented-adjacent (Oldsmar) + benchmarked; self-healing heals the *monitoring pipeline*, and physical actuation is limited to safe-stop.

---

## Appendix A: Missing Information Checklist
Items to confirm before/early in development:
- [ ] Exact pump model + rated current/voltage (sizes INA219 shunt + relay).
- [ ] Confirmed SWaT/WADI dataset access (or approved substitute).
- [ ] Target demo venue: power, water, network reality.
- [ ] Backend host: on-Pi vs laptop vs cloud for the demo.
- [ ] Auth scope: how many roles/users actually needed.
- [ ] Whether a closed-loop water return is used (affects dry-run staging).
- [ ] LSTM training data source for the *pump* twin (bench-collected vs synthetic).
- [ ] Acceptable false-isolation rate threshold (defines RL reward tuning target).
- [ ] Ledger: hash-chain (default) vs full Hyperledger (only if multi-party justified).
- [ ] Branding/theme for the dashboard (logo, palette) if any.

## Appendix B: Questions to Clarify Before Development
1. Is the **primary graded artifact** the live demo, the paper, or both equally? (Shifts effort between P6 and P7.)
2. Must the dashboard support **multiple devices** at submission, or is single-device acceptable with multi-device as future work?
3. What is the **minimum acceptable attribution accuracy** for the demo vs the paper?
4. Is a **real blockchain** required, or is a tamper-evident hash-chain sufficient? (Strongly recommend the latter unless multi-party trust is a stated requirement.)
5. How adversarial must the evaluation be — is the **white-box adaptive attacker** in scope for submission or future work?
6. Are there **safety sign-offs** needed for water+electronics at the venue?
7. Is **offline/sim-only** an acceptable fallback if hardware fails, for grading purposes?
8. Who are the **actual dashboard users** at review time (operator persona vs examiner) — drives which panels lead.

## Appendix C: Feature Priority Matrix (MoSCoW)
| Feature | Must | Should | Could | Won't (now) |
|---------|:---:|:---:|:---:|:---:|
| F1 Live telemetry ingest | Yes | | | |
| F2 Preprocessing | Yes | | | |
| F3 Anomaly + attribution | Yes | | | |
| F4 Dynamic trust | Yes | | | |
| F5 Trust-filtered prognosis | Yes | | | |
| F6 RL decision (+fallback) | Yes | | | |
| F7 Self-heal + substitution | Yes | | | |
| F8 Safe actuation | Yes | | | |
| F10 Real-time dashboard | Yes | | | |
| F12 Demo scenario injection | Yes | | | |
| F9 Tamper-evident ledger | | Yes | | |
| F11 Admin/RBAC/config | | Yes | | |
| Multi-device fleet view | | | Yes | |
| Alert routing (SMS/Slack) | | | Yes | |
| Full Hyperledger consensus | | | | Yes |
| OTA model updates | | | | Yes |

## Appendix D: Bill of Materials (BOM)
Target ≤ ₹10,000. Reality-checked (front-end audit applied).

| Item | Approx ₹ | Role | Note |
|------|--------:|------|------|
| Raspberry Pi 4 (4 GB) | 4,500 | Edge node | Runs acquisition + inference + actuation |
| 12 V DC pump + tubing + 2 reservoirs | 350 | Monitored machine | Dry-run via emptying source |
| MCP3008 ADC | 150 | Analog reads (SPI) | For ADXL335, MQ-135 |
| DS18B20 (temperature) | 120 | Ch1 | 1-Wire; kept separate from humidity |
| DHT22 (humidity) | 300 | Ch4 | Digital |
| ADXL335 accelerometer | 250 | Ch2 (vibration) | Analog→ADC |
| BMP180 pressure (I2C) | 200 | Ch3 (pressure) | **Proxy** — atmospheric, labelled |
| MQ-135 gas | 150 | Ch5 (gas) | **Proxy** — VOC/CO2, labelled |
| INA219 current+power (I2C) | 200 | Ch6 (current) | **Replaces ACS712** (sub-1 A resolution) |
| Relay + buzzer + LEDs | 300 | Actuation | Pump stop, alert, status |
| Breadboard, jumpers, 12 V supply, MicroSD | 1,200 | Wiring/power/OS | |
| **Total** | **~7,700** | | Under budget with contingency |

## Appendix E: Security & Authentication
- **AuthN:** Token-based login (JWT) for the dashboard; credentials for MQTT clients.
- **AuthZ (RBAC):** Roles — *Operator* (read + acknowledge), *Analyst* (read + forensics/export), *Admin* (config, device registration, user mgmt, scenario injection). Every control/admin/inject endpoint checks role.
- **Transport:** TLS on REST/WebSocket in any networked deployment; MQTT with credentials (TLS where supported).
- **Integrity:** Hash-chained ledger (FR-L); verifier run on demand + on load.
- **Auditing:** All privileged actions (config change, injection, RBAC denials) are themselves logged to the ledger.
- **Demo scoping:** For a localhost demo, credentials may be simplified but RBAC logic must still be demonstrable (P4-AUTH, P5-UI-S3).

## Appendix F: Data Flow Diagram Notes
- **DFD-1 (acquisition):** Sensors → drivers → sampler → local buffer → MQTT publish. Trust boundary: everything before publish is on the trusted edge node.
- **DFD-2 (edge inference):** window → {anomaly, trust, LSTM} → state vector → RL → self-heal → {actuation, decision+ledger publish}. This whole loop is edge-local for latency and safety.
- **DFD-3 (backend):** MQTT subscribe → {time-series store, ledger store} → WebSocket push + REST serve. Trust boundary: authn/authz at the API/WS edge.
- **DFD-4 (client):** WebSocket live + REST history → React state → render. No secrets client-side; tokens short-lived.
- **Critical path callout:** the *safety* path (dry-run → safe-stop) must never traverse the backend/cloud — it is fully edge-resident so network loss cannot prevent a stop.

---

## Final: Development-Ready PRD Summary

SHTAPM is a buildable, testable, demonstrable cyber-physical system that keeps a remote pump correctly monitored and safely running when a sensor fails or is falsified — attributing which, healing autonomously around it, stopping safely when it must, and proving every decision immutably — all surfaced through an enterprise-grade real-time dashboard.

This PRD provides: the full requirement set (functional + non-functional), a compute-placement architecture that puts safety and healing at the edge, a granular seven-phase build plan (P0 spikes → P7 evaluation) with **exhaustive Happy/Edge/Sad test cases at every phase including hardware-to-pixel E2E**, a graded live-demo script with a never-fail fallback, honest proxy/scoping guardrails for defensibility, and complete BOM, security, and DFD appendices.

**It is ready to hand to a developer and begin Phase 0.**
