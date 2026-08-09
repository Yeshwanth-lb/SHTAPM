# Document 03 — App Flow (Navigation & User Journey Map) *(enhanced)*
### SHTAPM Admin Dashboard — routes, journeys, and Aurora-native states
**Companion to:** PRD v1.0 · TRD (02) · UI/UX "Aurora" (04) · Backend Schema (05) · Implementation Plan (06)
**Status:** Build-ready · **Version:** 1.1 (adds Ambient Health Field transitions + Aurora-native empty/error states)

> Functionality and routes are unchanged from v1.0. **v1.1** describes how navigation, state changes, and every empty/error/edge state express themselves in the Aurora design language (Doc 04) — the living mesh background, glass bento tiles, and bloom/drift motion — so the *feel* of moving through the app is specified, not just the structure.

---

## 03.1 Pages / routes

| Route | Page | Access | Purpose |
|-------|------|--------|---------|
| `/login` | Login | Public | Authenticate; on success bloom into `/overview`. |
| `/` → `/overview` | Overview (default) | All | Fleet/device bento: health hero, live mini-charts, active alerts, system health. |
| `/device/:id` | Device Detail (**live cockpit**) | All | Full live telemetry, trust constellation, health/RUL, RL action log, self-heal status, ledger stream, inject controls — the curated bento (Doc 04 §04.5). |
| `/alerts` | Alerts | All | Sortable/filterable alert history (severity + attribution + reason). |
| `/ledger` | Audit Ledger | analyst, admin | Hash-chained event log; verify (teal cascade); export. |
| `/analytics` | Analytics | analyst, admin | Trends, confusion matrix, uptime-vs-compromise curves. |
| `/devices` | Device Management | admin | Register/edit/decommission; assign ownership. |
| `/settings` | Settings | admin | Thresholds, trust weights, sample rate, retention. |
| `/users` | User Management | admin | CRUD users, assign roles. |
| `/system` | System Health | admin | MQTT, DB, WS clients, live E2E latency, uptime. |
| `*` | Not Found | — | Graceful glass 404. |

## 03.2 Navigation structure
- **Left sidebar (persistent glass rail):** brand · Overview · Devices · Alerts · Ledger · Analytics · (admin) Device Mgmt / Settings / Users / System. Frosted-glass rail floating over the aurora; active item carries a soft accent glow; collapsible to an icon rail (tablet).
- **Top bar (floating glass strip):** device selector (in device context) · global connection indicator (WS + MQTT dot: green/amber/rose glow) · **live latency chip** (teal <1s → amber → rose) · notifications bell (unacked count) · user menu (role badge, logout) · theme + "reduce transparency" + motion toggles.
- **Breadcrumbs:** on nested pages (`Devices / Pump-01 / Live`), muted, letter-spaced.
- **Ambient Health Field is global:** the aurora mesh behind *all* pages reflects the currently focused device's (or fleet's) health — serene teal-violet when healthy, breathing amber on warning, slow rose heartbeat on critical (Doc 04 §04.5). Navigation never resets it abruptly; it crossfades over ~1.5s.

## 03.3 Auth flow
```
/login → submit
  → POST /api/auth/login
     ├─ 200: store access(in-mem)+refresh(httpOnly cookie) → aurora blooms, route → /overview
     └─ 401: inline glass error "Invalid credentials", gentle shake (motion-safe: color only)
Access expiring → silent POST /api/auth/refresh (rotating) → continue seamlessly
Refresh invalid/expired → toast "session expired" → fade to /login (intended route preserved)
Role gating → unauthorized route → redirect /overview + "Not permitted" toast
Logout → clear tokens, close WS, aurora dims, fade to /login
```
**Login screen aesthetic:** a single centered glass card floating over a slow, calm teal-violet aurora — the app "breathing" before you even log in. Massive thin wordmark; minimal fields; one primary glass button.

## 03.4 Hardware-to-dashboard flow (a device coming online) — Aurora-native
```
1. Edge boots → MQTT connect → retained status "online" (LWT armed).
2. Backend subscriber sees status → updates device row → emits WS device_status{online}.
3. Overview/Detail: the device's glass tile transitions grey→alive — a soft teal glow blooms
   around its border, the "connecting…" shimmer skeleton dissolves.
4. First telemetry frame (≤1 s) → six luminous sensor lines begin drawing from the right;
   trust constellation orbs ignite to steady teal; health hero numeral fades in; RUL starts counting.
5. If the edge drops → LWT "offline" → tile's glow cools to rose, charts freeze with a
   "last seen {ts}" frosted overlay, an alert blooms, and (if this is the focused device)
   the ambient aurora shifts toward rose.
```
*The "device comes alive" bloom is deliberately gorgeous — it's the demo's opening beat (PRD §18.4 step 1).*

## 03.5 Core user journeys

### Journey A — View live telemetry (Operator)
```
Login → aurora bloom → Overview → click "Pump-01" tile (tile lifts, then expands into cockpit)
 → Device Detail: WS subscribes (telemetry/decision/ledger for :id)
 → six luminous lines stream at 1 Hz; trust constellation calm teal; health "Healthy"; RUL counting
 → hover a line → frosted mini-tooltip blooms (mono value + timestamp)
 → no action needed; latency chip glows teal <1s; the whole screen feels like it's exhaling.
Empty/offline: device tile shows "Offline — last seen 12:04:33" frosted overlay + calm reconnect note.
```

### Journey B — Witness detect → attribute → self-heal (Analyst, the demo path)
```
Device Detail → tactile "Inject Scenario" toggle (RBAC: analyst/admin) → "Spoof: Pressure (constant)"
 → POST /api/devices/:id/inject → backend publishes command → edge applies spoof
 → within ≤3 windows: the pressure line's tile warms with a rose inner glow and the line
   shimmers ("this signal is lying"); the pressure trust orb shrinks + cools; alert blooms:
   "ATTACK — physics violation (pressure inconsistent with current)"; rig buzzer/LED fire
 → RL Action Log: an entry blooms in at the top "Isolate: pressure"; the pressure line switches
   to DASHED VIOLET, its tile gains a purple aura, a pulsing "VIRTUAL" chip appears;
   health prediction never drops
 → Ledger stream: blocks bloom in for each step
Analyst clicks the alert → a glass side-panel blooms: full attribution, trust timeline, related ledger blocks.
```

### Journey C — Register a new device (Admin)
```
Devices → "Add Device" → glass form (name, device_id, location, owner, sensor set)
 → POST /api/devices → 201 → new tile blooms in as "Offline — awaiting first connection"
 → admin flashes DEVICE_ID into edge .env → edge boots → status online (Flow 03.4)
 → tile ignites teal; admin verifies six channels in Detail.
Sad: duplicate device_id → 409 "Device ID already exists" → field glows rose, input preserved.
```

## 03.6 Edge / empty / error states — all Aurora-native (must all be designed)

| Condition | Where | Aurora expression |
|-----------|-------|-------------------|
| No devices yet | Overview | Calm empty glass tile, faint aurora, one glowing CTA ("Add your first device" / "No devices assigned"). |
| Device never connected | Tile / Detail | Frosted "Offline — awaiting first connection"; shimmer-skeleton charts; grey (not rose) glow. |
| Device went offline | Detail | Lines freeze + dim; "Last seen {ts}" frosted overlay; tile glow cools to rose; ambient aurora shifts rose if focused; auto-recover blooms back on reconnect. |
| WebSocket dropped | Top bar | Connection dot → amber "Reconnecting…"; exponential backoff; **no blank screen**; buffered REST history still viewable; aurora unaffected. |
| MQTT broker down | System + top bar | Rose "Broker unreachable"; live tiles show frosted "stale (paused)" veil; auto-recover. |
| Backend 5xx (history) | REST panel | Inline glass error card + "Retry" glow button; live WS tiles unaffected. |
| No telemetry in range | Analytics / charts | "No data for selected range" calm empty state; axes fade, no broken line. |
| Sensor channel unhealthy | Detail | That line greys + "sensor fault" chip; others keep streaming; self-heal may switch it to VIRTUAL (violet). |
| Unauthorized route | Any | Fade-redirect to Overview + toast; never a raw 403 page. |
| Session expired | Global | Toast + fade to login; intended route preserved for return. |
| Demo/replay mode | Global | Subtle frosted "DEMO — replaying recorded session" chip pinned top-center so replay is never mistaken for live. |
| Reduced-transparency mode | Global | Glass → near-opaque surfaces; aurora recedes to canvas edges only; full data parity (accessibility). |

---

### App-flow intent, in one line
Every route, journey, and failure state is not just defined but *choreographed* in Aurora — tiles bloom, glows warm and cool with health, the background breathes with system state — so navigating SHTAPM feels calm and alive while never hiding a single offline device, dropped socket, or unauthorized action.
