---
version: 1
slug: "frontend-src-pages-controlroompage-tsx"
primary_target: "frontend/src/pages/ControlRoomPage.tsx"
related_targets: ["frontend/src/styles/premium.css"]
---

## Scope
Control Room (home route) and the shared shell/theme every page inherits. Visitor mode: Operate.

## Audience, job, constraints
Operator (and presentation evaluators) must read pump health, see which sensor lies and why, and act. Laptop or projector; nothing under 12px; AA contrast; ISA-101: colour only for abnormal state.

## Direction contract
THESIS: The Control Room proves an attack by showing the contradiction between two physical witnesses, live; it refuses the category default of a grey grid of same-weight metric cards with one accent colour.
OWN-WORLD: Flight-operations wall taken only as type, palette, density and one move. Deep space-navy ground (#0a0f1c family), a solid mission-blue rail (#163a8a family) carrying navigation, warm white type, mission-blue accent for selection; red/amber/green/violet only for state. Barlow for UI, Barlow Semi Condensed for numerals and headings, tabular figures. Square-ish 8px corners, 1px navy hairlines, no glow, no glass.
STORY: The visitor sees the master caution and the physics coupling first; understands a healthy pump as two witnesses moving together; watches an attack tear them apart in red; trusts the system because it names the lying sensor and the twin takes over.
FIRST VIEWPORT: Rail left (brand + nav). Top: master caution band, full width. Below it, full width: the "Two witnesses" coupling trace (current and vibration on shared IDLE/RUNNING lanes, last ~2 min, verdict to the right). Then the six instruments in a 3x2 grid (big numerals, trust bar), with demo scenarios, pump relay and transport in the right column.
FORM: Pinned by the user (mission control); concept-seed not run because the direction was pinned. seed: none (unavailable)
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
