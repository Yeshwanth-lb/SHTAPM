# edge/ — Raspberry Pi edge node

Runs the **entire** `sense → detect → attribute → decide → heal → actuate` loop.
Per **D003** this loop never depends on the backend/cloud/network.

Structure (TRD §02.6):

| Dir | Purpose | Phase |
|-----|---------|-------|
| `drivers/` | one driver per sensor: `read() -> {value, unit, ts, healthy}` | P1 |
| `acquisition/` | 1 Hz sampler, ring buffer, MQTT publisher | P1 |
| `pipeline/` | preprocess, anomaly, trust, prognosis (LSTM), rl_agent, self_heal | P2/P3 |
| `actuation/` | relay, watchdog, safe_stop | P1/P3 |
| `ledger/` | SHA-256 hash-chain writer (**D004**) | P3 |
| `config/` | `device.yaml`, `thresholds.yaml` | P0 stubs |
| `models/` | `iforest.pkl`, `lstm.pt`, `dqn.zip` (generated; git-ignored) | P2/P3 |
| `tests/` | pytest | all |

**P0 status:** directory skeleton + config stubs only. No functional code yet.
Runtime dependencies are pinned in P1–P3. Hardware spikes require the Pi/rig
and are tracked as hardware-blocked in `../project-state/TODO.md`.
