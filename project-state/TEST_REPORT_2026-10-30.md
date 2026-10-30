# SHTAPM — Final test report (2026-10-30)

One report for everything that was run on the final code. Every number below was
produced on 2026-10-30 on the project laptop (Windows 11, Python 3.14, Node 20,
Mosquitto 2.x running as a service) at the commit that contains this file.

## 1. Verdict

| Area | Result |
|---|---|
| Python automated tests (edge, backend, simulator) | **2,358 passed, 0 failed**, 8 skipped, 4 expected failures |
| Dashboard automated tests (Vitest) | **259 passed, 0 failed** (36 files) |
| TypeScript type check (`tsc --noEmit`) | **clean** |
| ESLint (frontend) | **clean** |
| Ruff (Python lint) | **clean** |
| Black (Python format) | **clean** (346 files; two files were re-formatted today, formatting only) |
| Report build (89 pages) | **0 errors, 0 warnings, 0 layout problems** |
| IEEE paper (6 pages) and journal paper (28 pages) builds | **0 errors, 0 warnings, 0 layout problems** |
| Hardware-in-the-loop scenarios (11) | **10 verified, 1 expected limit** (HT-11) |

No test failed. Nothing was skipped silently; every skip and expected failure is
explained in sections 3 and 4.

## 2. Automated test results

Command: `python -m pytest -q` from the repository root (8 min 25 s).

| Suite | Passed | Skipped | Expected failures | Failed |
|---|---:|---:|---:|---:|
| `edge/tests` | 1,926 | 8 | 4 | 0 |
| `backend/tests` | 415 | 0 | 0 | 0 |
| `simulator/tests` | 17 | 0 | 0 | 0 |
| **Python total** | **2,358** | **8** | **4** | **0** |
| `frontend` (Vitest, 36 files) | 259 | 0 | 0 | 0 |

By subsystem (test functions in the repository): sensor drivers, acquisition and
edge runtime 357; preprocessing, detection and injection 184; trust and
attribution 150; isolation, self-healing and digital twin 169; safety supervisor
and relay 47; prognosis and response-policy modules 940; backend 381; simulator 17;
dashboard 259.

What the suites cover: driver conversion and failure handling (including the ADC
rail check and DHT22 reopen), the 5 s dead-sensor rule, MQTT buffering and replay,
the Isolation Forest and channel flag policy, the Beta trust update and bands,
operating-state attribution (hysteresis, suspect selection, impulse rejection),
isolation hysteresis and the 60 s substitution clock, the safety supervisor
(dry run, watchdog, latching, pin refusal), live scenario injection, the ledger
(tamper and broken-link detection, canonical payloads), authentication and
role-based access (login, rotation, denial auditing), the WebSocket, the
REST API, alerts, condition rollup, and the dashboard components.

## 3. Skipped tests (8)

All eight are in `edge/tests/test_dht22_driver.py` (`TestFindIIODevice` and the
auto-discovery cases of `TestDHT22HumidityReader`). They build fake kernel
directories named `iio:deviceN`, and **Windows does not allow `:` in file
names**. They are Linux-only and run on the Raspberry Pi. All broker-dependent
tests ran (the local Mosquitto service was up) and passed.

## 4. Expected failures (4)

`edge/tests/test_p2_acceptance.py`: P2-ANOM-H1, P2-ANOM-E1 (synthetic fixture
stream has a 12.7 % clean flag rate against 0.1 % on real bench data), P2-TRUST-H1
(`c` definition, decision U01) and P2-TRUST-H2 (structural limitation accepted in
D015). Each is marked `xfail` with its recorded reason; none is an unexplained
failure.

## 5. Static checks

```
cd frontend; npx tsc --noEmit        # exit 0
cd frontend; npx eslint .            # exit 0
python -m ruff check .               # All checks passed
python -m black --check edge backend simulator scripts   # 346 files unchanged
```
Black initially flagged `edge/eval/bench_twin_training.py` and
`scripts/preflight.py`; both were re-formatted (a conditional-expression layout,
no behaviour change) so the project's CI stays green.

## 6. Hardware-in-the-loop (real Raspberry Pi, real sensors)

| ID | Scenario | Expected | Observed |
|---|---|---|---|
| HT-01 | Sensor diagnostic on the Pi | all sensors in range | verified |
| HT-02 | Motor cycled by hand, live dashboard | six channels at 1 Hz, no attack | verified |
| HT-03 | DHT22 dropout when the motor starts | last value held | verified |
| HT-04 | Constant spoof to 0 A, motor running, 40 s | attack, isolation, VIRTUAL | ATTACK after 23 s; isolated |
| HT-05 | Bias +0.8 A, motor off, 40 s | attack on current | ATTACK after 19 s, no false trip |
| HT-06 | Stuck current sensor, motor running | fault, not attack | FAULT |
| HT-07 | Attack held beyond the 60 s budget | latched Safe Pump-Stop | pump trip, latched |
| HT-08 | Second isolation after a release | no premature trip | verified (D050) |
| HT-09 | Ledger verification of the session | chain intact | 200 of 200 blocks |
| HT-10 | Loose converter wire (all channels at the rail) | readings rejected | verified (D055) |
| HT-11 | Small within-state bias on running current | not attributable | as expected (physical limit) |

The relay is the in-memory relay and gas is the emulated source (see
`HANDOVER.md`); neither affects any result above.

## 7. Evaluation on recorded data (final baseline, 51.4 min, 2,609 frames)

Re-run on 2026-10-30 with `python scripts/final_eval.py` on the current code
(`results/final_baseline_current/`; `results/` is gitignored).

| Measure | Result |
|---|---|
| False attacks on clean data | **0 / 2,552** channel-windows |
| Faults kept as faults (episode) | 23 / 27 (85 %) |
| State-crossing attacks attributed (episode / settled) | 32 / 44 (73 %) / 29 / 44 (66 %) |
| Within-state attacks | 0 / 23 (documented physical limit) |
| Balanced accuracy, operating-state rule vs trend-sign rule | 79 % vs 60 % |
| Hold-out clean flag rate / Malicious channel-windows | 19.9 % / 0 |
| Detector: faults / attacks detected at 0.95 | 60/60 / 120/120, median delay 6 samples |
| Self-heal: isolated | 10/12 bias, 10/12 spoof (out of sample, 0 false isolations) |
| Self-heal: error without / with twin | 0.60 A → 0.079 A (bias), 0.57 A → 0.12 A (spoof) |

Detail: `project-state/EVALUATION_RESULTS_2026-10-26.md` section 9.

## 8. Documents

| Document | Build | Result |
|---|---|---|
| `report/` (89 pages) | `pdflatex` ×3 | 0 errors, 0 warnings, 0 over/underfull boxes; all 49 references cited and resolved |
| `paper/` (IEEE, 6 pages) | `pdflatex` ×3 | 0 errors, 0 warnings, 0 boxes; 26 references |
| `paper_journal/` (28 pages) | `pdflatex` ×3 | 0 errors, 0 warnings, 0 boxes; 49 references |

Text checks on the compiled PDFs: no unresolved references, no repeated words,
British spelling throughout. Text-overlap measurement (8-word runs, bodies only):
paper vs report 5.1 %; the new report vs the Phase-1 report 0.1 %; paper vs the
Phase-1 report 0.2 %. This is an own-text overlap estimate, **not** a Turnitin or
AI-detector result; those must be run by the college library.

## 9. Not tested, on purpose

- A physical relay and the real MQ-135 (not wired).
- A real pump and a real dry run (a DC motor stands in; dry-run is verified on
  injected frames).
- Broker authentication and TLS, PostgreSQL with TimescaleDB (the bench uses an
  unauthenticated broker and SQLite; the Postgres-only migration tests need Docker).
- Remaining-useful-life and the DQN policy are tested as modules but not deployed.

## 10. Reproduce

```
python -m pytest -q
cd frontend && npx vitest run && npx tsc --noEmit && npx eslint .
python -m ruff check . && python -m black --check edge backend simulator scripts
python scripts/final_eval.py final_baseline.jsonl     # needs the gitignored capture
```
