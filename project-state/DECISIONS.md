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

---

## UNDECIDED (must not be silently resolved — see CURRENT_STATE blockers)
- U01 — Beta-reputation trust-update formula + recovery dynamics (P2).
- U02 — Fault-vs-attack physics/correlation attribution rules + thresholds (P2).
- U03 — LSTM: one shared model or two (prognosis vs digital-twin) (P3); edge stores single `lstm.pt`.
- U04 — Digital-twin training-data source: bench-collected vs synthetic (P3).
- U05 — `divergence_threshold` + substitution uncertainty-cap values (P3).
- U06 — RL reward shaping + acceptable false-isolation rate (P3).
- U07 — SWaT/WADI dataset access vs TEP+bench substitute (P2/P7).
- U08 — Backend host for demo: on-Pi vs laptop (P0/P6).
- U09 — Pump model + rated current (sizes INA219 shunt/relay) (P1 hardware).
- U10 — Demo role/user count; MQTT credential/TLS scope for localhost demo (P4).
- U11 — Dashboard branding (logo/palette) beyond Aurora defaults (P5).
- U12 — Primary graded artifact: live demo vs paper (shifts P6/P7 weighting).
- U13 — White-box adaptive-adversary evaluation in submission scope or future (P7).
- U14 — `…/command` (scenario-inject) message payload is UNSPECIFIED in all docs (TRD §02.3 names the topic only). Blocks P4 injection (FR-A4/FR-D7). Not part of the M2 telemetry/decision/ledger freeze; do not invent.
