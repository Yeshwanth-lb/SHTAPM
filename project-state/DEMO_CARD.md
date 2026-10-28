# Demo card (one page, keep it next to the laptop)

Tested on the bench 2026-10-28 (D049, D050). Open the **Control Room**. Wait
for **NORMAL** before every scenario. Inject from **Device -> Scenario
injection**, then go straight back to the Control Room.

An attack is caught when **current and vibration contradict each other**.
Only that pair is physically linked on this bench.

| # | Motor | Scenario | Channel | Duration | Value | Expect (within ~25 s) |
|---|---|---|---|---|---|---|
| 1 | **ON** (30 s first) | Constant spoof | current | 40 | Spoofed value **0** | **ATTACK**: "current says idle, vibration says running"; CURR ATTACK; current ISOLATED + VIRTUAL; trust red |
| 2 | **OFF** (wait NORMAL) | Bias injection | current | 40 | Offset **0.8** (no minus) | **ATTACK**: "current says running, vibration says idle" |
| 3 | **ON** (30 s first) | Stuck sensor | vibration | 40 | -- | amber **FAULT** (not attack): anomaly the physics explains |

Measured: scenario 1 isolated in 23 s, scenario 2 in 19 s. Scenario 3 still
to be rehearsed.

After each attack: **Acknowledge**, wait for **NORMAL** (about 1-2 min), then
the next one. Finish with **Ledger -> Verify**.

## What to say

1. "Every sensor gets a live trust score. Watch current."
2. Attack: "The attacker tells the controller the pump stopped. Vibration
   proves it is running -- the physics is impossible, so it is an attack, not
   a fault. Trust drops, the sensor is isolated, and the digital twin rebuilds
   current from vibration. The pump keeps running."
3. Fault: "Same anomaly detector, but here the physics still agrees -- so the
   system calls it a FAULT and sends maintenance, not security."
4. Ledger: "Every step is a hash-chained block. Verify proves nobody edited it."

## Do NOT

- Ramp or Stealth injection: by design they stay inside normal behaviour; no
  sensor reading can tell them apart (state it as a known limit).
- Offset with the wrong sign: motor ON + positive offset, or motor OFF +
  negative offset, keeps both sensors agreeing -- nothing impossible to catch.
- Attacks on temperature / humidity / pressure / gas: detected at most as
  FAULT (no physical partner on this bench).

## If something goes wrong

- Caution says **NO DATA**: backend lost the Pi. Check the hotspot, restart the
  backend window.
- Hardware misbehaves: switch to the recorded session (DEMO_RUNBOOK.md,
  "Fallback") and say so.
