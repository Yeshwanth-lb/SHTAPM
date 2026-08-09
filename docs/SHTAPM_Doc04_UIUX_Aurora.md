# Document 04 — UI/UX Design Brief *(revised)*
### SHTAPM Admin Dashboard — "Aurora" Design Language
**Companion to:** SHTAPM PRD v1.0 · Technical Blueprint Docs 02–06 · **Supersedes:** Doc 04 (control-room draft)

> **What changed and what didn't.** The *functionality*, information architecture, routes, data contract, and every panel from Doc 03/05 remain exactly the same — same live charts, trust panel, RL action log, ledger stream, health/RUL, system metrics. What changes is the *skin and the feel*: we move from a rigid industrial console to **Aurora** — a blissful, glassmorphic, bento-grid interface that feels calm to watch and hyper-modern to use, in the lineage of Vercel, Stripe, and Linear. The data stays dense and useful; the presentation becomes ethereal.

---

## 04.1 Aesthetic Direction

**Aurora is "calm intelligence."** The dashboard should feel less like a control room and more like watching weather move across a still night sky — you glance at it and feel that the system is *breathing*, healthy, in flow. Everything floats on a deep, near-black canvas lit from within by slow, blurred color orbs. Widgets are frosted-glass **bento tiles** of varying sizes that snap into a satisfying modular grid. Typography is large, thin, and geometric, with generous whitespace so each number has room to feel important. Motion is slow, eased, and ambient — nothing darts or bounces; things *drift*, *bloom*, and *settle*.

The emotional target: **blissful vigilance.** When all is well, the screen is a serene teal-violet aurora and the operator feels calm. When something is wrong, the whole environment *responds* — the ambient light breathes amber, a tile's glass warms — so awareness is delivered through atmosphere before a single alert is read. The interface earns attention through *light and depth*, not clutter or hard color blocks.

**Principles**
- **Depth over borders.** Hierarchy comes from blur, translucency, and soft luminosity — not heavy lines or drop-shadow soup.
- **The background is alive but never distracting.** Aurora orbs move at 20–40 s cycles; you feel them more than you watch them.
- **One idea per tile.** Each bento box says one thing beautifully. Density lives *inside* tiles, calm lives *between* them.
- **Status is atmosphere.** Health shifts the ambient palette globally; individual anomalies warm their own tile's glass. Color still always pairs with shape + label (accessibility, §04.6).
- **Restraint is luxury.** Thin weights, ample negative space, a tiny accent vocabulary. The premium feeling comes from what we *leave out*.

---

## 04.2 Color Palette (design tokens)

Aurora is **dark-primary**. The base is a deep, slightly blue-black void; surfaces are *translucent glass* over it; light comes from the mesh-gradient orbs and from status luminosity.

### Canvas & aurora
| Token | Value | Use |
|-------|-------|-----|
| `--void` | `#07090E` | Deepest background base (behind everything) |
| `--void-2` | `#0A0E15` | Subtle vertical vignette toward edges |
| `--aurora-teal` | `#2DD4BF` | Healthy orb A |
| `--aurora-violet` | `#7C6BF5` | Healthy orb B |
| `--aurora-blue` | `#3B82F6` | Healthy orb C / accent light |
| `--aurora-amber` | `#F5A524` | Anomaly/warning orb (breathing) |
| `--aurora-rose` | `#F43F6E` | Critical orb (slow pulse) |
> The **ambient mesh** composes 3–4 of these as huge (60–90vmin), heavily blurred (`filter: blur(120px)`) radial orbs drifting on independent slow loops. Their *mix* is driven by system health (see §04.5 "Ambient Health Field").

### Glass surfaces (translucent — always over the aurora)
| Token | Value | Use |
|-------|-------|-----|
| `--glass-1` | `rgba(255,255,255,0.045)` | Bento tile fill (frosted) |
| `--glass-2` | `rgba(255,255,255,0.075)` | Raised/nested glass, hover |
| `--glass-inset` | `rgba(0,0,0,0.25)` | Inset wells (log areas, inputs) |
| `--glass-border` | `rgba(255,255,255,0.10)` | Ultra-thin 1px translucent tile border |
| `--glass-border-strong` | `rgba(255,255,255,0.18)` | Focus/active tile edge |
| `--glass-highlight` | `rgba(255,255,255,0.14)` | Top-edge specular sheen (1px) |
| `--blur-tile` | `blur(20px) saturate(140%)` | `backdrop-filter` for tiles |
| `--blur-modal` | `blur(32px) saturate(160%)` | `backdrop-filter` for overlays |

### Text
| Token | Value | Use |
|-------|-------|-----|
| `--text-hero` | `rgba(255,255,255,0.96)` | Massive metric numerals |
| `--text-primary` | `rgba(233,240,247,0.88)` | Body |
| `--text-secondary` | `rgba(233,240,247,0.58)` | Labels |
| `--text-muted` | `rgba(233,240,247,0.34)` | Timestamps, hints |

### Status (semantic — luminous, not flat)
| Token | Core | Glow (for auras/rings) | Meaning |
|-------|------|------------------------|---------|
| `--status-healthy` | `#34E4B0` | `rgba(52,228,176,0.35)` | Trusted ≥0.7 / Healthy / Online |
| `--status-warning` | `#F5B740` | `rgba(245,183,64,0.38)` | Suspicious 0.4–0.7 / Warning |
| `--status-critical` | `#FF5C7A` | `rgba(255,92,122,0.40)` | Malicious <0.4 / Critical / Offline |
| `--status-virtual` | `#B98BFF` | `rgba(185,139,255,0.40)` | **Virtual-substituted channel** (reconstructed, not measured) |
| `--status-info` | `#5AC8FF` | `rgba(90,200,255,0.35)` | Neutral events |

> **Meaning is unchanged from the prior draft** — the green/amber/red *bands* and the exclusive purple for VIRTUAL are preserved 1:1. Only their expression changes: status now radiates as a soft **glow/ring** on glass rather than a solid fill, so a critical state *lights up* its tile like an ember behind frosted glass.

**Light theme (optional "Daybreak"):** `--void` → `#EEF1F6` with pale aurora (lowered opacity), glass becomes `rgba(255,255,255,0.55)` over the light mesh, text inverts. Dark is the tuned default.

---

## 04.3 Typography

Geometric, modern, thin-forward — the Vercel/Linear signature.

- **Display / metrics:** **Geist** (primary) → fallback **Satoshi** → **Plus Jakarta Sans** → `system-ui`. Hero numerals use weight **200–300** at very large sizes so a trust score of `0.94` feels like a serene statement, not a readout.
- **UI text:** Geist / Plus Jakarta Sans, weights 400/500, generous letter-spacing at small sizes for that airy, premium cadence.
- **Numeric alignment:** `font-variant-numeric: tabular-nums` on all live-updating figures so digits don't jitter as they tick.
- **Monospace (ledger hashes, raw payloads, logs):** **Geist Mono** → `ui-monospace, JetBrains Mono`. Hashes middle-truncated (`a1b2…9f0c`), full on hover/copy.

**Type scale**
| Role | Size / weight | Notes |
|------|---------------|-------|
| Hero metric | 56–72px / 200 | RUL, headline trust, big health % — thin + luminous |
| Metric | 32–40px / 250 | Tile primary numbers |
| H1 | 22px / 500 | Page title |
| H2 | 16px / 500 | Tile titles (often uppercase, letter-spaced, `--text-secondary`) |
| Body | 14px / 400 | |
| Label | 12px / 500, +0.04em tracking | Tile captions |
| Mono | 12–13px / 400 | Ledger, logs |

> **Whitespace is a first-class design element.** Tile titles sit quietly in a corner; the hero number owns the center; nothing crowds the edges. Let numbers breathe.

---

## 04.4 Component Style

### Bento grid (the structural signature)
- A **12-column bento grid**, ~16–20px gap, tiles spanning varied sizes (1×1, 2×1, 2×2, 3×2, 4×2) that **snap** into place. The Device Detail "cockpit" is a curated bento arrangement (§04.5) rather than rigid columns.
- Tiles have **radius 20–24px** (soft, pillowy), never sharp.
- Entrance: tiles **bloom in** with a subtle scale (0.98→1) + opacity ease over ~400ms, gently staggered — a satisfying "settle."
- Rearranging (responsive reflow) is animated with FLIP so tiles glide, never teleport.

### Glass tiles (glassmorphism)
```
background: var(--glass-1);
backdrop-filter: var(--blur-tile);         /* frosted */
border: 1px solid var(--glass-border);
border-radius: 22px;
box-shadow:
  inset 0 1px 0 var(--glass-highlight),    /* top specular sheen */
  0 8px 40px rgba(0,0,0,0.45);             /* soft floating depth */
```
- **Ultra-thin translucent 1px border** + a 1px inner top highlight give the "pane of frosted glass catching light" look.
- **Hover:** glass brightens to `--glass-2`, border → `--glass-border-strong`, and the tile lifts ~2px with a slightly larger soft shadow (it floats toward you). ~180ms ease.
- **Status expression:** an anomalous tile grows a soft inner **glow ring** in its status color (e.g., `box-shadow: inset 0 0 0 1px var(--status-critical), 0 0 40px var(--status-critical-glow)`), like an ember warming the frosted pane — no hard fills.

### Tactile interactive elements (subtle neumorphism / claymorphism)
Reserved **only** for controls the user physically toggles — chiefly the **Virtual Substitution toggle**, threshold sliders, and the mode switch:
- Soft dual inner shadow to feel *pressable* (a gentle clay button sitting in the glass):
  `box-shadow: inset 2px 2px 6px rgba(0,0,0,0.35), inset -2px -2px 6px rgba(255,255,255,0.06);`
- On press: shadows invert (pushed-in), a soft haptic-like 90ms ease, and the control emits a faint status-colored glow. Toggling a sensor to VIRTUAL makes the switch bloom purple as it "clicks" — it should feel like flipping a real hardware switch.
- Used sparingly — tactile cues are the exception that makes interaction feel physical; everything else stays flat glass.

### Other components
| Element | Aurora spec |
|---------|-------------|
| **Buttons** | Primary: translucent glass pill with a faint accent-lit border + soft glow on hover; text `--text-hero`. Secondary: bare glass. Destructive: rose-tinted glass + rose glow. Radius 12px, thin weight, focus ring = accent glow. |
| **Chips/badges** | Frosted pill, status color at ~18% behind luminous text; a soft matching glow. "VIRTUAL" chip = purple glass with a gentle pulse. |
| **Tables** | Live inside a glass tile over an `--glass-inset` well; header row barely-there uppercase labels; 44px rows; hover = row glass-brighten; status as a **glowing dot + label**, never a full-row flood. Numerics tabular-nums, right-aligned. |
| **Inputs/sliders** | Inset glass wells; focus = accent glow ring; slider handle is a small clay knob (tactile). |
| **Toasts** | Floating frosted card, top-right, status-glow left edge, slow bloom-in / fade-out. |
| **Skeletons** | Frosted shimmer with a slow aurora-tinted sweep — even loading feels blissful. |
| **Modals/popovers** | Stronger `--blur-modal`, slightly brighter glass, backdrop dims the aurora to ~40%. |

---

## 04.5 Data-Visualization UI — inside the glass bento

This is where dense telemetry meets ethereal presentation. Every visualization lives *inside* a glass bento tile, over the living aurora, rendered so it feels calm even while carrying real data.

### The Ambient Health Field (the "blissful" engine)
The whole app's background mesh is bound to overall system health — a single global state driving the orb palette:
- **Healthy →** teal + violet + blue orbs drift slowly (30–40s loops), low saturation, serene. The room feels like it's exhaling.
- **Suspicious/Warning →** one orb crossfades toward `--aurora-amber` and the mesh's motion *breathes* a touch faster (a slow ~4s in-out pulse). Awareness arrives as a mood shift before you read anything.
- **Critical →** a `--aurora-rose` orb blooms low and slow behind the content with a heartbeat-like pulse (~1.2s), and global saturation lifts slightly. Never a flash, never strobing — dread delivered gently.
- Transitions between health states crossfade over ~1.5s so the environment *glides* between moods. (`prefers-reduced-motion` freezes orb motion to a static gradient while keeping the color mapping.)

### Device Detail — the bento cockpit (arrangement)
A curated bento, e.g.:
- **Hero tile (2×2):** current machine **Health** as a huge thin numeral / word + a soft radial health aura; RUL/failure-ETA beneath.
- **Six live sensor tiles (1×1 each)** or one **wide multi-spark tile (4×2):** the live line charts.
- **Trust tile (2×2):** the six-sensor trust field.
- **RL Action Log (2×2 tall) + Ledger stream (2×2 tall):** side-by-side glass wells.
- **System-health micro-tiles (1×1):** MQTT ●, WS clients, sample rate, live E2E latency.

### Live Line Charts (uPlot inside glass)
- **Look:** last 60s scrolling window on a transparent plot (the aurora shows faintly *through* the glass behind the line — depth). The line is a fine **1.5px luminous stroke** in the sensor's assigned hue, with a soft **outer glow** (drop-shadow) so it looks like a light-trail, and a whisper-thin gradient area fill (~6% → 0%) fading downward.
- **Live cursor:** a soft glowing orb pulses gently at the newest point (a tiny "breathing" dot), leaving a faint comet-trail as it advances. New points **ease in** over ~140ms — the line *grows*, never jumps.
- **Axes:** almost invisible — muted tabular-nums labels, hairline gridlines at ~6% white. The chart should feel like a luminous thread floating in glass, not a graph in a box.
- **State expression (the disambiguation, made beautiful *and* legible):**
  - *Fault* → the tile's glass warms with a faint **amber inner glow**; the line shifts toward amber.
  - *Attack* → faint **rose glow** + the affected line briefly shimmers/distorts (a subtle "this signal is lying" wobble) — unsettling on purpose.
  - *VIRTUAL (self-healed)* → the line switches to a **dashed violet** stroke, the tile gains a soft **purple aura**, and a small pulsing "VIRTUAL" chip sits in the corner. It visibly reads as *reconstructed light* — clearly not a raw sensor. This is the money moment of the demo; make it gorgeous and unmistakable.
- Hover crosshair → a frosted mini-tooltip (mono value + timestamp) blooms in.

### Trust Panel (the six-sensor "constellation")
Reimagined from bars into something blissful yet dense:
- **Primary form — radial trust field:** six nodes arranged in a gentle ring (or arc) inside the tile, each a soft luminous orb whose **size + glow intensity encode the trust score** and whose **color** is the band (green/amber/red). A trusted sensor glows a calm steady teal; a suspicious one dims to a flickering amber; a compromised one collapses to a small, cold rose ember. The numeric score sits beside each node in thin tabular-nums.
- **Motion:** on a trust drop, the node **shrinks and cools** over ~500ms with an eased crossfade — you *see* trust drain out of it. Recovery = it slowly re-brightens and swells back. It should feel like watching stars dim and rekindle.
- **Dense fallback:** a compact horizontal "trust equalizer" (six luminous bars) is available for users who prefer exact bars; same color/label semantics. Both encode value by **length/size + color + number**, never color alone.

### Trust / RUL Gauge
- A thin **radial ring** (ECharts) with a soft gradient arc (teal→amber→rose) and a luminous progress fill; the value in a huge thin numeral at center. The ring's leading tip carries a gentle glow that eases to its new position — no snapping needle. On entering Warning/Critical the ring emits a single soft bloom (not a loop).

### RL Action Log (inside a glass well)
- A reverse-chronological, virtualized stream inside an `--glass-inset` well. Each entry **blooms in at the top** (soft slide + fade, ~220ms) and the older entries drift down — new decisions feel like they *arrive*, calmly.
- Row anatomy: a small status-glow dot · an action glyph (isolate / reduce-weight / alert / safe-stop) · the action in clean sentence case · an affected-sensor chip · a muted mono timestamp right-aligned. A `safe_stop` entry gets a subtly stronger rose glow so the eye finds the serious moment.
- The most recent entry keeps a faint lingering aura for a second after arrival — a gentle "just happened" cue.

### Ledger Stream (inside a glass well)
- Same well treatment. Each block: a validity tick (soft teal glow when the chain verifies) · `event_type` · a **mono truncated hash** (`a1b2…9f0c`, full on hover/copy) · timestamp. On "Verify," valid blocks pulse teal in sequence (a satisfying cascade); a **tampered block** breaks the cascade — its row cools to rose, shows a broken-chain glyph, and a hairline "fracture" appears between it and the previous block. Immutability, made visible and a little magical.

### System-Health Micro-tiles
- Tiny glass 1×1 tiles: MQTT status dot, WS client count, sample rate, and **live E2E latency** as a thin numeral that glows teal (<1s) → amber (1–2s) → rose (>2s). Honest and calm; the latency tile is the system's quiet pulse.

**Global motion grammar:** ease-out, 140–500ms, transform + opacity + filter only (GPU-friendly). Ambient orbs on long independent loops. Everything *blooms, drifts, settles* — nothing snaps. All non-essential motion is gated by `prefers-reduced-motion`.

---

## 04.6 Responsive & Accessibility

**Responsive (bento reflow)**
- **≥1280 (primary):** full curated bento cockpit; hero + charts + trust + logs all visible; aurora at full life.
- **≥768 (tablet):** bento **re-tiles** via FLIP into fewer columns; large tiles become full-width, small tiles pair up; charts stack; aurora simplifies to 2 orbs for performance. Sidebar → icon rail.
- **≥360 (mobile):** single-column stack of glass tiles, read-focused; aurora reduced to a static gradient; the live cockpit is best on tablet/desktop but remains legible.

**Accessibility (WCAG 2.1 AA — non-negotiable, and harder with glass, so handled deliberately)**
- **Contrast:** because text sits on translucent glass over a moving mesh, every tile carries a subtle internal contrast floor (a faint darkening under text regions) so **text↔background contrast stays ≥4.5:1 at all aurora phases.** We verify against the *brightest* possible orb position, not just the average.
- **Never color alone:** every status is color **+ shape/size/label** — trust nodes vary in size and carry numbers; VIRTUAL always shows the dashed line + "VIRTUAL" chip; alerts carry icons + text. Critical for red/green colorblind operators.
- **Motion safety:** `prefers-reduced-motion` freezes aurora drift and disables bloom/pulse (keeping instant state changes + color); nothing strobes; the critical "heartbeat" is slow (~1.2s) and gentle, never a seizure risk.
- **Glass legibility fallback:** a user setting "Reduce transparency" swaps frosted glass for near-opaque solid surfaces (keeping the aurora only at the canvas edges) for low-vision users — full parity, no lost data.
- **Keyboard + SR:** complete keyboard nav with a visible accent-glow focus ring on every interactive element; ARIA live-regions announce new critical alerts; charts expose an accessible data-table view; the tactile toggles are real buttons with proper `aria-pressed`.
- **Performance UX:** cap live chart points (ring buffer 60–120), virtualize logs, animate only transform/opacity/filter, and throttle aurora repaints — the bliss must never cost a dropped frame or a jank on the 1 Hz stream.

---

### Design intent, in one line
**Aurora keeps every number, panel, and safety cue from the working dashboard — and wraps them in frosted-glass bento tiles floating over a living, health-reactive aurora, so watching critical infrastructure feels less like staring at a console and more like watching a calm sky that quietly warns you the moment the weather turns.**
