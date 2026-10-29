# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: an operator watching one industrial pump (bench: a DC motor with six sensors) from a laptop, who must tell at a glance whether the machine is healthy, whether a sensor is failing, or whether a sensor is being spoofed, and act (acknowledge, stop the pump, read the evidence). Secondary, and decisive for this build: evaluators at a final-year project presentation, including a senior UI/UX designer, watching the dashboard live on a laptop or a projector while attacks are injected.

## Product Purpose
SHTAPM (Self-Healing Trust-Aware Pump Monitoring) gives every sensor a live trust score, decides whether an anomaly is a FAULT or an ATTACK from the pump's own physics, isolates a lying sensor and substitutes a digital-twin reconstruction, stops the pump safely when trust cannot be restored, and records every step in a tamper-evident SHA-256 ledger. Success: an attack is visibly caught and explained within ~25 s, with no false alarms on a healthy pump.

## Positioning
Attribution by physical contradiction: current and vibration are a physically coupled pair, so a sensor that claims "idle" while the other proves "running" is a lie, not a fault. Neighbouring anomaly dashboards flag "something is odd"; this one says which sensor is lying and why.

## Operating Context
Live bench: Raspberry Pi 5 edge (detection, trust, physics check, twin, safety) -> MQTT -> FastAPI backend (auth, alerts, ledger, DB) -> React dashboard. Demo flow: motor on, one-click rehearsed scenarios (spoof attack, bias attack, stuck fault), acknowledge, recovery, ledger verify. Pages: Control Room (home), Device, Devices, Decisions, History, Alerts, Ledger, Users, System, Settings.

## Capabilities and Constraints
Six channels: temperature, humidity (DHT22), vibration (ADXL335 via MCP3008), pressure (BMP280), current (INA219) real; gas (MQ-135) is a labelled placeholder. Only current and vibration are physically coupled, so only attacks on them can be attributed as attacks. Known limits stated openly: in-state attacks, ramp vs drift, stealth injection. Relay is simulated (no physical relay wired). Every number shown must come from a real endpoint; nothing is estimated for display.

## Brand Commitments
Name SHTAPM. Control-room discipline (ISA-101 style, D046): calm when normal, colour only for abnormal states, every state also a word or shape. The user pinned a "mission control" direction on 2026-10-29: dark, high-contrast, bold, energetic; readable on laptop or projector.

## Evidence on Hand
Live data from the bench; bench evaluation results in project-state/EVALUATION_RESULTS_2026-10-26.md (section 9); rehearsed scenarios in project-state/DEMO_CARD.md. No customers, testimonials or benchmarks exist and none may be invented.

## Product Principles
1. Prove, don't claim: show the contradiction that makes an attack an attack.
2. Calm until it matters: a healthy pump reads quiet; an abnormal state is unmistakable.
3. Every figure is real: no decorative numbers, no estimates dressed as data.
4. Readable from across a room: large type, strong contrast, one focal point per state.

## Accessibility & Inclusion
WCAG AA contrast (projector use makes it a floor, not a goal); state never by colour alone; reduced motion honoured (OS setting and the in-app switch).
