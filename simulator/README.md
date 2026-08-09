# simulator/ — hardware-free telemetry source (D005)

Dev/replay telemetry source so the backend/frontend path is buildable and
demoable **without** the Raspberry Pi/bench rig, and as the live-demo fallback
(PRD R1/R2). **Not** the real edge acquisition — that is P1 under `edge/`.
Kept isolated from Pi drivers on purpose (D008).

- `generator.py` — `TelemetrySimulator`: deterministic (seeded) samples of the
  six frozen channels, emitting the M2 `TelemetryMessage` contract verbatim.
- `publisher.py` — `MqttTelemetryPublisher`: publishes to
  `shtapm/{device_id}/telemetry` (QoS 0, TRD §02.3); client injected.
- `__main__.py` — 1 Hz CLI runner (builds a paho-mqtt client from env).

## Contract reuse
The simulator imports the canonical contract from `backend/app/schemas`
(D006/D007) rather than duplicating field names. Until a shared contract
package exists (a possible cleanup when edge P1 also needs it — D008), run with
`backend` on `PYTHONPATH`.

## Run (needs a broker; live path proven in M3.2+)
```bash
pip install -r simulator/requirements.txt
PYTHONPATH=backend:. python -m simulator
```

## Test (deterministic, no broker)
```bash
PYTHONPATH=backend:. pytest simulator/tests -q
```

## Scope
M3.1 = generator + publisher + tests only. No anomaly/trust/ML/decision/ledger
logic. Baseline means/ranges in `generator.py` are simulator-chosen plausible
bench values (datasheet-bounded), not authoritative spec numbers.
