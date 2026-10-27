# AC10 — Doc06 Happy/Edge/Sad coverage audit

## ⚠️ STATUS AS OF 2026-10-27 (read first; the 2026-09-24 audit below is kept as the record)

| Phase | Rows | Covered | Partial | Not covered | N/A · by design |
|---|---|---|---|---|---|
| **Total 2026-10-27** | **77** | **35** | **31** | **9** | **2** |
| Total 2026-09-24 | 77 | 17 | 34 | 21 | 5 |

Rows that changed, with the evidence (same strict standard as below: a test
that drives a fake does not count for a claim about physical hardware):

| Row | Was | Now | Evidence |
|---|---|---|---|
| P1-2 missing var -> named boot error | PARTIAL | COVERED | edge: `test_replay_source.py::test_missing_fit_window_count_names_the_variable` (D040) |
| P1-3 fonts load offline | NOT COVERED (defect) | COVERED | Geist vendored 2026-10-26; `test_every_font_face_url_resolves_to_a_vendored_file` no longer xfail |
| P1-4 `SAMPLE_RATE_HZ="x"` -> named error | PARTIAL | COVERED | `test_malformed_sample_rate_names_the_variable` (D040) |
| P3-3 manual relay stop/start | N/A | PARTIAL | software: `test_relay_api.py`, `test_safety_supervisor.py` (D041); physical relay not yet wired |
| P3-9 kill edge -> pump OFF | N/A | PARTIAL | stall: `test_watchdog_stops_a_running_pump_without_frames`; crash: systemd `ExecStopPost` hook `test_systemd_off_hook` (D041); physical pending |
| P4-2 inject via REST | NOT COVERED | COVERED | `backend/tests/test_inject_api.py` (D032) |
| P4-6 WS reconnect, no dup storm | PARTIAL | COVERED | `useDeviceTelemetry.session.test.ts` "reconnect loop" (backoff 1 s -> 2 s, one socket per attempt) |
| P5-3 health -> aurora colour | NOT COVERED | COVERED | `aurora-budget.test.tsx` (tone + field palette per state) |
| P5-8 `VITE_REDUCE_TRANSPARENCY` | NOT COVERED (not implemented) | COVERED | implemented (`lib/visualPrefs.ts`, opaque glass, no data change); `visualPrefs.test.ts` |
| P5-9 WS drop -> "reconnecting" | PARTIAL | COVERED | hook test above: state `closed` drives "Stream disconnected" + the reconnecting notice |
| P5-10 history 500 -> error + retry | PARTIAL | COVERED | `pages.test.tsx` "turns a backend 500 into an error card whose retry really refetches" |
| P5-12 expired session -> login, return route kept | PARTIAL | COVERED | guard remembers the page, login shows a notice and returns there (`app/returnRoute.test.tsx`); an in-page notice instead of a global toast |
| P6-5 rapid attack -> heal -> fault ordering | NOT COVERED | COVERED | `pages.test.tsx` "shows the newest of a rapid attack -> heal -> fault sequence"; the decisions page now polls every 2 s |
| P6-8 <= 4 orbs / <= 6 blur layers | NOT COVERED | PARTIAL | orb count asserted (`aurora-budget.test.tsx`); blur layers and fps need a real browser |
| P6-10 latency > 2 s -> critical | NOT COVERED | COVERED | `SystemPage.latency.test.tsx` "marks the target missed when p95 is over 2 s" |
| P6-11 fps < 50 -> auto-downgrade | NOT COVERED (not implemented) | COVERED (logic) | `FpsGuard` sheds glow/blur and freezes orbs after 2 s under 50 fps; `visualPrefs.test.ts` with synthetic frames |
| P7-2 UI inject -> isolate -> VIRTUAL | NOT COVERED | PARTIAL | inject path + twin exist; current goes VIRTUAL (`self_heal_eval`, D039); no single automated E2E test; pressure still has no twin |
| P7-3 empty reservoir -> safe stop | N/A | PARTIAL | dry-run rule + relay (D041) tested on injected frames; the bench has no pump/reservoir to produce a physical dry run |
| P7-8 pump dead -> fallback | PARTIAL | COVERED | recorded-session profile `EDGE_SOURCE=replay` (D040), `test_replay_source.py`; still to rehearse (AC8) |
| P7-10 broker killed -> auto-recover | PARTIAL | COVERED | `backend/tests/test_mqtt_reconnect.py` (every consumer re-subscribes); edge buffer/replay already covered |
| P8-2 pre-flight self-check | NOT COVERED (not implemented) | COVERED | `scripts/preflight.py`, `backend/tests/test_preflight.py` (against the real routers) |
| P8-6 one service fails -> named | NOT COVERED | COVERED | pre-flight names the failing check (broker, database, edge, ledger, latency) |
| P8-7 SD/DB corruption recovery | NOT COVERED | COVERED (doc) | `DEMO_RUNBOOK.md` "Recovery: SD card or database corruption" |

Also fixed while auditing: the Settings "Reduce motion" switch stored a
preference that no stylesheet read; it now drives `data-motion` CSS.

Still open, by kind: physical/browser-only rows (P1-1 compose bring-up, P2-1/P2-6
Postgres, P3-1/2/8 bench evidence, P5-5 tablet, P5-6/P6-1 soak/fps, P8-4
projector) need the rig, Docker or a real browser; P5-7 list virtualization,
P5-11 redirect + toast (an in-page RBAC message today) is frontend work; P3-7 /
P7-9 (one dead sensor withholds every frame) remain N/A by the frozen contract.

---

## Original audit (2026-09-24)

**Scope:** every row of the Happy/Edge/Sad tables in
`docs/SHTAPM_Doc06_ImplementationPlan.md` (77 rows across 8 phases), mapped to
the automated tests that actually exercise it. The standard is strict: a test
that only drives a fake or stub does **not** count as COVERED for a claim about
physical hardware, a browser, or visual rendering.

**Classification**
- **COVERED** — an automated test asserts the row's expected behaviour.
- **PARTIAL** — some of the behaviour is tested, or it is shown only by bench evidence and not by an automated test. The note says what is missing.
- **NOT COVERED** — no test. Rows marked *not implemented* have no code behind them yet.
- **N/A · BY DESIGN** — deliberately blocked or contradicted by a recorded decision.

Tests added by this audit (new files only, no source changes):
`backend/tests/test_ac10_backend_gaps.py`, `edge/tests/test_ac10_edge_gaps.py`,
`edge/tests/test_ac10_repo_offline.py`. **22 passed, 1 xfail** (a real defect,
see P1-3).

---

## Summary

| Phase | Rows | Covered | Partial | Not covered | N/A · by design |
|---|---|---|---|---|---|
| 1 Setup / env | 7 | 0 | 5 | 2 | 0 |
| 2 DB & auth | 10 | 6 | 2 | 2 | 0 |
| 3 Hardware / firmware | 9 | 3 | 3 | 0 | 3 |
| 4 Backend / WS / MQTT | 11 | 6 | 4 | 1 | 0 |
| 5 Frontend core | 12 | 0 | 8 | 4 | 0 |
| 6 UI polish / live viz | 11 | 2 | 4 | 5 | 0 |
| 7 E2E hardware → pixel | 10 | 0 | 5 | 3 | 2 |
| 8 Deploy / demo prep | 7 | 0 | 3 | 4 | 0 |
| **Total** | **77** | **17** | **34** | **21** | **5** |

Six of the 17 COVERED rows became covered through tests added in this audit.
**Verdict on AC10 ("every Must feature passes Happy/Edge/Sad"): not met.**
Backend, auth, and edge software behaviour are well covered. The frontend,
visual, performance, and hardware-to-pixel rows are mostly partial or
untested, and five rows cannot pass under the current design.

---

## Row-by-row matrix

### Phase 1 — Project setup, repo, env vars

| # | Case | Status | Evidence / gap |
|---|---|---|---|
| 1 | Happy · `docker-compose up` offline | PARTIAL | `test_ac10_repo_offline.py::test_compose_defines_the_four_demo_services` checks the file's structure. An actual bring-up has never been run by any test, and docker isn't installed on the dev laptop. |
| 2 | Happy · missing var → boot error naming it | PARTIAL | Backend: `test_database_settings.py::test_missing_password_names_both_ways_to_fix_it`, `test_ac10_backend_gaps.py::test_missing_jwt_secret_fails_at_boot_naming_the_variable`. Edge: `P2_FIT_WINDOW_COUNT` is required by `edge/main.py` but untested (the file was under active edit, so no test was added). |
| 3 | Happy · fonts load offline (Geist renders) | NOT COVERED — **defect** | `test_ac10_repo_offline.py::test_every_font_face_url_resolves_to_a_vendored_file` is **xfail(strict)**. The Geist woff2 binaries were never vendored: `frontend/src/assets/fonts/` holds only `FONTS.md`, so every `@font-face` 404s and the UI falls back to system-ui. |
| 4 | Edge · `SAMPLE_RATE_HZ="x"` → validation error at boot | PARTIAL | `edge/main.py` calls `float(...)` at startup, so it does fail at boot, but with `could not convert string to float: 'x'`, which doesn't name the variable. Untested. |
| 5 | Edge · port already in use | NOT COVERED | No detection or report exists. |
| 6 | Sad · missing `.env` → refuse to boot | PARTIAL | The backend raises for each missing required var. Compose refuses to start without the DB password (`test_compose_refuses_to_start_the_db_without_a_password`). "No half-start" across services is untested. |
| 7 | Sad · corrupt compose → fail fast in CI | PARTIAL | New text-level compose tests run in CI through pytest. There's no full YAML parse, because PyYAML isn't a dependency. |

### Phase 2 — Database schema & auth

| # | Case | Status | Evidence / gap |
|---|---|---|---|
| 1 | Happy · migrate up/down | NOT COVERED | `alembic/versions/0001_initial_schema.py` is Postgres-only. Tests use `create_all` on SQLite. |
| 2 | Happy · login valid → access+refresh, role in token | COVERED | `test_auth_api.py::test_login_success_returns_tokens`, `test_ac10_backend_gaps.py::test_login_access_token_carries_the_users_role` |
| 3 | Happy · hypertable insert + rollup; `devices.health_state` updates | PARTIAL | `test_telemetry_persistence.py::test_persist_creates_device_and_reading` (SQLite, no hypertable or rollup). No producer ever writes `health_state`, so it stays at its default. |
| 4 | Edge · refresh at expiry boundary | COVERED | `test_auth_service.py::test_rotate_refresh_token_happy_path`, `::test_rotate_expired_refresh_token_raises`, `test_auth_api.py::test_refresh_rotates_tokens` |
| 5 | Edge · operator queries another owner's device → empty | PARTIAL | Scoping is enforced in the app layer: `test_rest_api.py::test_operator_lists_only_owned_devices`, `::test_alerts_filter_by_unowned_device_is_empty_not_error`. DB-level RLS was deferred (`app/api/deps.py`). A single-device GET returns 404, not empty. |
| 6 | Edge · 10k bulk insert within budget; index used | NOT COVERED | Needs Postgres. |
| 7 | Sad · wrong password → generic 401 | COVERED | `test_auth_api.py::test_login_wrong_password_is_generic_401`, `::test_login_unknown_email_is_same_generic_401` |
| 8 | Sad · reused rotated refresh → 401 + family revoked | COVERED | `test_auth_api.py::test_refresh_reuse_after_rotation_is_401`, `test_auth_service.py::test_reused_rotated_refresh_token_revokes_all_user_tokens` |
| 9 | Sad · non-admin writes thresholds → 403 + audit | COVERED | `test_ac10_backend_gaps.py::test_operator_patching_thresholds_is_403_audited_and_changes_nothing` |
| 10 | Sad · SQLi in params | COVERED | `test_ac10_backend_gaps.py::test_sql_injection_in_path_and_query_params_is_inert`, `::test_sql_injection_in_login_email_is_a_plain_401` (SQLite; ORM-parameterized) |

### Phase 3 — Hardware / firmware & connectivity

| # | Case | Status | Evidence / gap |
|---|---|---|---|
| 1 | Happy · 10-min six-channel run, <1% dropped | PARTIAL | Bench evidence only: a 7.18 h capture with no gap over 5 s (`BENCH_LOAD_VALIDATION.md`). Not automated. Gas is simulated. **The bench was down on 2026-09-24:** a missing `torch` crash-loops the service, and BMP280 I²C reads fail. |
| 2 | Happy · INA219 idle vs load | PARTIAL | Bench evidence: 0.78 A under load vs about 0 A idle (`BENCH_LOAD_VALIDATION.md` §2). Unit tests mock I²C. |
| 3 | Happy · manual relay stop/start | N/A · BY DESIGN | No actuation is wired, by instruction (`CURRENT_STATE.md`, TODO AC4). `test_relay.py` drives a fake actuator only. |
| 4 | Edge · 10 Hz burst stable | COVERED | `test_ac10_edge_gaps.py::test_10hz_burst_for_60s_stays_bounded_and_contiguous` (software) |
| 5 | Edge · broker down 30 s → buffered, replayed in order | COVERED | `test_ac10_edge_gaps.py::test_30s_broker_outage_at_1hz_replays_every_frame_in_order`, `::test_default_retention_outlasts_a_30s_outage_at_every_supported_rate`, `test_mqtt_publisher.py::test_fifo_replay_in_order_on_reconnect` |
| 6 | Edge · sensor at range boundary → clamped/flagged | COVERED | `test_drivers.py::test_below_range_clamped_healthy`, `::test_above_range_clamped_healthy` |
| 7 | Sad · unplug sensor mid-run → that channel unhealthy, others continue | N/A · BY DESIGN | Contradicted by the frozen contract, which has no per-channel health field, so the Sampler withholds the **whole frame** (`test_sampler.py::test_unhealthy_channel_no_frame_but_readings_preserved`; `BENCH_LOAD_VALIDATION.md` §4). DS18B20 is only an optional alternate now (D028). |
| 8 | Sad · loose I²C SDA → handled error + reconnect | PARTIAL | Mocked recovery is tested: `test_bmp280_driver.py::test_driver_read_recovers_after_failure`, `test_ina219_driver.py::test_driver_read_recovers_after_failure`. The physical failure observed on 2026-09-24 (BMP280 `Remote I/O error`) did not recover. |
| 9 | Sad · kill edge process → watchdog → pump OFF | N/A · BY DESIGN | `test_watchdog.py::test_deadman_process_failure_forces_off` is software-only, and no relay is wired. |

### Phase 4 — Backend API & WebSocket/MQTT

| # | Case | Status | Evidence / gap |
|---|---|---|---|
| 1 | Happy · MQTT→DB→WS, in order, <1 s | PARTIAL | `test_integration_ws.py::test_mqtt_to_backend_to_ws` skips without a broker and asserts no latency. |
| 2 | Happy · inject via REST → command + audit + ledger | NOT COVERED — *not implemented* | No inject endpoint exists in `backend/app/api/`. |
| 3 | Happy · ledger verify intact | COVERED | `test_ledger_api.py::test_admin_verify_valid_chain` |
| 4 | Happy · `system_health` frame carries health + `e2e_latency_ms` | PARTIAL | The REST route is covered (`test_rest_api.py::test_admin_reads_system_health`, `test_latency_tracker.py`). No WS `system_health` frame is emitted or tested. |
| 5 | Edge · 5 concurrent WS clients | PARTIAL | `test_ac10_backend_gaps.py::test_five_concurrent_ws_subscribers_each_receive_every_frame_in_order` covers broadcaster fan-out. Real sockets and "no lag beyond budget" are not measured. |
| 6 | Edge · WS reconnect, no dup storm | PARTIAL | `useDeviceTelemetry.test.ts` covers close-code classification (terminal vs retryable). The reconnect loop itself is untested. |
| 7 | Edge · empty history range → 200 + empty | COVERED | `test_rest_api.py::test_get_readings_out_of_range_is_empty` |
| 8 | Sad · malformed MQTT payload | COVERED | `test_mqtt_consumer.py::test_malformed_json_handled_safely`, `::test_contract_invalid_rejected` |
| 9 | Sad · tampered ledger → `{valid:false, broken_at:n}` | COVERED | `test_ledger.py::test_verify_detects_tampered_payload` (asserts `broken_at == 1`), `test_ledger_api.py::test_admin_verify_detects_tamper` |
| 10 | Sad · unauthenticated WS connect rejected | COVERED | `test_ws_endpoint.py::test_ws_requires_token`, `::test_ws_rejects_invalid_token` |
| 11 | Sad · operator hits admin REST → 403 + audit | COVERED | `test_ac10_backend_gaps.py::test_operator_hitting_admin_users_route_is_403_and_audited`, `test_rest_api.py::test_non_admin_cannot_list_users` |

### Phase 5 — Frontend dashboard core (no frontend tests added: `frontend/src` was out of scope)

| # | Case | Status | Evidence / gap |
|---|---|---|---|
| 1 | Happy · login → overview | PARTIAL | `routes.test.tsx` ("shows the login screen when signed out"), `RequireAuth.test.tsx`. No full login→overview flow test, and visuals are untested. |
| 2 | Happy · device detail → WS live values | PARTIAL | `useTelemetryWebSocket.test.ts` ("connects and stores telemetry keyed by device"). `DevicePage` itself is not rendered in any test. |
| 3 | Happy · health → aurora colour mapping | NOT COVERED | |
| 4 | Happy · ack alert (optimistic + confirm) | PARTIAL | Backend: `test_rest_api.py::test_ack_alert_sets_fields`. No frontend ack test. |
| 5 | Edge · tablet 768px re-tile | NOT COVERED | Visual. |
| 6 | Edge · 60-min session, no leak | PARTIAL | `useDeviceTelemetry.test.ts` ("caps the window, dropping the OLDEST points"). No soak test. |
| 7 | Edge · burst of 50 events, virtualized lists | NOT COVERED — *not implemented* | No list virtualization in `frontend/src`. |
| 8 | Edge · `VITE_REDUCE_TRANSPARENCY=on` | NOT COVERED — *not implemented* | Not referenced anywhere in `frontend/src`. |
| 9 | Sad · WS drops → "Reconnecting…" | PARTIAL | The string exists (`DevicePage.tsx`, `useDeviceTelemetry.ts`). Only close codes are tested. |
| 10 | Sad · backend 500 on history → error card + retry | PARTIAL | `pages.test.tsx` DevicesPage ("surfaces a load failure as an error"), `useApiResource.test.ts`. A 500 on the History page itself is untested. |
| 11 | Sad · operator opens `/users` → redirect + toast | PARTIAL | `pages.test.tsx` UsersPage ("treats 403 as RBAC working"). The implementation shows an in-page message instead of a redirect, and no toast system exists. |
| 12 | Sad · expired session → toast + login, return route kept | PARTIAL | `useApiResource.test.ts` ("flags a 401 distinctly"), `RequireAuth.test.tsx`. No toast, and the return route is untested. |

### Phase 6 — UI polish & live visualisation

| # | Case | Status | Evidence / gap |
|---|---|---|---|
| 1 | Happy · 1 Hz stream at 60 fps | NOT COVERED | Performance, needs a browser. |
| 2 | Happy · trust drop → orb shrinks | PARTIAL | `TrustConstellation.test.tsx` ("scales with trust"). The alert bloom is untested. |
| 3 | Happy · VIRTUAL channel styling + chip | PARTIAL | `SensorCard.test.tsx` "VIRTUAL substitution state" (chip, not colour-only). The dashed violet line and aura are not asserted. |
| 4 | Happy · ledger verify cascade | PARTIAL | `pages.test.tsx` LedgerPage renders blocks. The animation is untested. |
| 5 | Edge · rapid attack→heal→fault ordering | NOT COVERED | |
| 6 | Edge · `prefers-reduced-motion` | PARTIAL | CSS media queries exist; `pages.test.tsx` ("exposes a real, working motion preference"). |
| 7 | Edge · colour-blind distinguishable | COVERED | `ChannelProvenanceBadge.test.tsx` (not colour-only), `SensorCard.test.tsx` ("does not encode the state by colour alone"), `TrustConstellation.test.tsx` (size encodes value) |
| 8 | Edge · ≤4 orbs / ≤6 blur layers, fps ≥55 | NOT COVERED | |
| 9 | Sad · bad/NaN data point | COVERED | `useDeviceTelemetry.test.ts` ("rejects a non-numeric sensor value"), `Sparkline.test.tsx` ("produces no NaN for a single point") |
| 10 | Sad · latency >2 s → chip turns rose | NOT COVERED | `SystemPage.tsx` shows `e2e_latency_ms`, but no threshold behaviour is tested. |
| 11 | Sad · fps <50 → auto-downgrade | NOT COVERED — *not implemented* | No fps monitoring in `frontend/src`. |

### Phase 7 — End-to-end (hardware → pixel)

| # | Case | Status | Evidence / gap |
|---|---|---|---|
| 1 | Happy · physical vibration change visible <2 s | PARTIAL | Edge→backend latency is measured (`test_latency_tracker.py`, AC6). The browser leg is not. Manual check only. |
| 2 | Happy · UI-inject pressure spoof → isolate → VIRTUAL | NOT COVERED — *not implemented* | No UI/REST inject path exists (P4-2). The twin is deployed only for `current` (`BENCH_LOAD_VALIDATION.md` §7), so pressure cannot go VIRTUAL. |
| 3 | Happy · empty reservoir → physical safe-stop | N/A · BY DESIGN | No dry-run detection and no actuation wired. Escalation is disabled (`divergence_threshold=+inf`, U05). TODO AC4. |
| 4 | Happy · tamper ledger live → verify fractures | PARTIAL | Backend: `test_decision_ledger.py::test_tamper_is_still_caught_after_real_events`. The UI is untested. |
| 5 | Edge · venue Wi-Fi drop → buffer, reconnect, no loss | PARTIAL | Edge replay is covered (P3-5). UI reconnect is only partly covered (P4-6). |
| 6 | Edge · full-load latency <2 s | NOT COVERED | The browser leg is unmeasured. |
| 7 | Edge · rapid attack→heal→fault ordering | NOT COVERED | |
| 8 | Sad · pump dead → fallback/replay | PARTIAL | The simulator path is tested (`test_integration_backend_mqtt.py::test_simulator_to_backend_ingestion`, broker-gated). No recorded-session replay exists (`FALLBACK_REPLAY_PATH` is declared in `.env.example` but unused). Never rehearsed (AC8). |
| 9 | Sad · sensor unplugged mid-demo → flagged, VIRTUAL, demo continues | N/A · BY DESIGN | Unplugging **any** sensor stops **all** telemetry: the Sampler withholds whole frames (see P3-7), so self-heal never sees the dead channel. |
| 10 | Sad · broker killed mid-demo → degraded, auto-recover | PARTIAL | Edge buffer/replay is covered. Backend MQTT reconnect relies on paho defaults and is untested. |

### Phase 8 — Deployment & demo prep

| # | Case | Status | Evidence / gap |
|---|---|---|---|
| 1 | Happy · offline profile bring-up | PARTIAL | `test_ac10_repo_offline.py::test_frontend_html_and_css_reference_no_external_urls` passes. Fonts are missing (P1-3). A full bring-up is untested. |
| 2 | Happy · pre-flight self-check | NOT COVERED — *not implemented* | Only `/healthz` exists; there is no pre-flight script. |
| 3 | Edge · cold boot, ordered start | PARTIAL | `test_ac10_repo_offline.py::test_compose_encodes_the_documented_startup_order` checks the file. It has never been executed. |
| 4 | Edge · projector legibility | NOT COVERED | Manual. |
| 5 | Edge · weak GPU, `VITE_AURORA_MOTION=reduced` | PARTIAL | `pages.test.tsx` (motion preference). |
| 6 | Sad · one service fails → self-check names it | NOT COVERED — *not implemented* | Depends on P8-2. |
| 7 | Sad · SD/DB corruption on Pi → documented recovery | NOT COVERED | No recovery runbook found. No replay (P7-8). |

---

## Top gaps that matter for the final demo

1. **Unplugging or losing one sensor stops the whole live stream** (P3-7, P7-9). The Sampler publishes only when all six channels are healthy, so a single DHT22 dropout (motor EMI) or a loose BMP280 blanks the dashboard, and self-heal never gets to act. This is the most likely live hiccup. Fixing it needs a decision (for example, a per-channel health field in the contract, D006/D007), not a test.
2. **There is no inject path** (P4-2, P7-2). The PRD demo's "UI-inject spoof → isolate → VIRTUAL" story cannot be performed live. The twin also covers only `current`, so a pressure spoof couldn't go VIRTUAL anyway.
3. **Offline demo readiness is untested and partly broken**: the Geist fonts were never vendored (xfail), there's no pre-flight self-check, the replay fallback doesn't exist, and a full `docker compose up` bring-up has never been run (P1-1/3, P7-8, P8-2).

Also worth fixing before the demo: the edge startup crash when `torch` is missing (observed 2026-09-24, being fixed separately), and the unmeasured browser leg of latency (P6-10, P7-6).
