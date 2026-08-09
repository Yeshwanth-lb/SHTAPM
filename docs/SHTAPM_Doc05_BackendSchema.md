# Document 05 — Backend Schema (Data Model & Auth Architecture) *(enhanced)*
### SHTAPM — telemetry, decisions, trust, ledger, users
**Companion to:** PRD v1.0 · TRD (02) · App Flow (03) · UI/UX "Aurora" (04) · Implementation Plan (06)
**Status:** Build-ready · **Version:** 1.1 (adds system-health rollup + continuous aggregates for Aurora/analytics)

> The relational + time-series model is unchanged in substance from v1.0. **v1.1** adds (a) a derived **health-rollup** feed so the frontend can drive the Ambient Health Field (Doc 04) without new safety logic, and (b) explicit **continuous aggregates** so the Analytics page and 60-min live buffers stay fast. The shared data contract is authoritative — firmware, backend, WS, and TS types all mirror these names.

---

## 05.1 Conventions
- All tables have `id` (UUID v4, PK) unless noted; timestamps `TIMESTAMPTZ` (UTC); units never stored as strings.
- Time-series tables (`sensor_readings`, `decisions`) are **TimescaleDB hypertables** partitioned on `ts`.
- Names mirror the shared contract (TRD §02.6) exactly.

## 05.2 Tables

### `users`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| email | TEXT UNIQUE NOT NULL | login id |
| password_hash | TEXT NOT NULL | bcrypt |
| full_name | TEXT | |
| role | ENUM('operator','analyst','admin') NOT NULL | RBAC |
| is_active | BOOL DEFAULT true | |
| created_at | TIMESTAMPTZ DEFAULT now() | |
| last_login_at | TIMESTAMPTZ | |

### `devices`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| device_id | TEXT UNIQUE NOT NULL | matches edge `DEVICE_ID` |
| name | TEXT NOT NULL | "Pump-01" |
| location | TEXT | "Lift Station A" |
| owner_user_id | UUID FK→users.id | ownership for RLS |
| status | ENUM('online','offline','degraded') DEFAULT 'offline' | from LWT |
| health_state | ENUM('healthy','warning','critical') DEFAULT 'healthy' | **latest rollup (drives Aurora)** |
| last_seen_at | TIMESTAMPTZ | |
| sample_rate_hz | INT DEFAULT 1 | |
| created_at | TIMESTAMPTZ DEFAULT now() | |
> `health_state` on `devices` is a denormalized cache of the newest `decisions.health_state` (updated by the subscriber) so Overview tiles + the ambient field render instantly without scanning the hypertable.

### `sensors` (per-device channel registry)
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| device_id | UUID FK→devices.id | |
| channel | ENUM('temperature','vibration','pressure','humidity','gas','current') | |
| part | TEXT | "DS18B20","INA219" |
| unit | TEXT | "°C","A" |
| is_proxy | BOOL DEFAULT false | pressure/gas = true (honest labelling) |
| display_hue | TEXT | Aurora line color token for this channel |
| UNIQUE(device_id, channel) | | |

### `sensor_readings` — **hypertable**
| Column | Type | Notes |
|--------|------|-------|
| ts | TIMESTAMPTZ NOT NULL | partition key |
| device_id | UUID FK→devices.id | |
| sample_seq | BIGINT | monotonic per device |
| temperature | REAL | |
| vibration | REAL | |
| pressure | REAL | |
| humidity | REAL | |
| gas | REAL | |
| current | REAL | |
| healthy_mask | INT | bitmask of per-channel sensor health |
| PRIMARY KEY (device_id, ts, sample_seq) | | |

### `decisions` — **hypertable** (event-driven pipeline output)
| Column | Type | Notes |
|--------|------|-------|
| ts | TIMESTAMPTZ NOT NULL | |
| device_id | UUID FK→devices.id | |
| anomaly_flag | BOOL | |
| anomaly_severity | REAL | 0–1 |
| attribution | ENUM('none','fault','attack') | disambiguation result |
| reason | TEXT | "physics violation: pressure vs current" |
| trust_temperature … trust_current | REAL ×6 | per-sensor scores 0–1 |
| health_state | ENUM('healthy','warning','critical') | drives device rollup + Aurora |
| failure_eta | REAL | cycles/seconds ahead |
| rl_action | ENUM('continue','reduce_weight','isolate','alert','safe_stop') | |
| isolated_channels | TEXT[] | |
| substituted_channels | TEXT[] | VIRTUAL channels (violet in UI) |
| PRIMARY KEY (device_id, ts) | | |

### `alerts`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| device_id | UUID FK→devices.id | |
| ts | TIMESTAMPTZ | |
| severity | ENUM('info','warning','critical') | |
| type | ENUM('fault','attack','system') | |
| channel | TEXT | affected sensor (nullable) |
| message | TEXT | |
| reason | TEXT | |
| acknowledged_by | UUID FK→users.id NULL | |
| acknowledged_at | TIMESTAMPTZ NULL | |

### `ledger_blocks` — tamper-evident chain
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| device_id | UUID FK→devices.id | |
| block_index | BIGINT | per-device sequence |
| ts | TIMESTAMPTZ | |
| event_type | TEXT | "trust_drop","isolate","safe_stop"… |
| payload | JSONB | event detail |
| payload_hash | TEXT | sha256(payload) |
| prev_hash | TEXT | link |
| this_hash | TEXT | sha256(index+ts+payload_hash+prev_hash) |
| UNIQUE(device_id, block_index) | | |

### `thresholds` (per-device config)
| Column | Type | Notes |
|--------|------|-------|
| device_id | UUID PK/FK→devices.id | |
| trust_trusted_min | REAL DEFAULT 0.7 | |
| trust_malicious_max | REAL DEFAULT 0.4 | |
| trust_w_consistency | REAL DEFAULT 0.4 | |
| trust_w_correlation | REAL DEFAULT 0.3 | |
| trust_w_reliability | REAL DEFAULT 0.3 | |
| window_size | INT DEFAULT 30 | |
| substitution_max_seconds | INT DEFAULT 60 | bound for FR-H3 |
| divergence_threshold | REAL | escalate-to-safe-stop trigger |
| updated_by | UUID FK→users.id | |
| updated_at | TIMESTAMPTZ | |

### `audit_log` (privileged actions)
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users.id | |
| action | TEXT | "config_update","scenario_inject","rbac_denied" |
| target | TEXT | |
| detail | JSONB | |
| ts | TIMESTAMPTZ DEFAULT now() | |

### `refresh_tokens`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users.id | |
| token_hash | TEXT | rotating |
| expires_at | TIMESTAMPTZ | |
| revoked | BOOL DEFAULT false | |

## 05.3 Continuous aggregates & rollups (new in v1.1)
- **`readings_1min` (continuous aggregate):** per-device, per-channel 1-minute avg/min/max over `sensor_readings`, used by `/analytics` and long-range history so the Analytics page never scans raw high-res data.
- **`decisions_5min` (continuous aggregate):** counts of `attribution` = attack/fault, mean trust, time-in-each-health-state — powers the confusion-matrix and uptime-vs-compromise views.
- **Device health rollup:** on each `decisions` insert, the subscriber updates `devices.health_state` + `devices.last_seen_at`. A lightweight `system_health` WS frame is emitted carrying the current `health_state` so the frontend can crossfade the Ambient Health Field. **No new safety logic — pure presentation-state derivation.**

## 05.4 Relationships
```
users 1───* devices          (owner_user_id)
users 1───* refresh_tokens
users 1───* audit_log
devices 1───* sensors
devices 1───* sensor_readings
devices 1───* decisions
devices 1───* alerts
devices 1───* ledger_blocks
devices 1───1 thresholds
users 1───* alerts            (acknowledged_by, nullable)
```

## 05.5 Indexes
| Table | Index | Why |
|-------|-------|-----|
| sensor_readings | hypertable time partition on `ts`; `(device_id, ts DESC)` | latest-N + range per device |
| decisions | `(device_id, ts DESC)`; partial `WHERE attribution='attack'` | recent decisions + attack filter |
| alerts | `(device_id, ts DESC)`; `(acknowledged_at) WHERE acknowledged_at IS NULL` | unacked badge |
| ledger_blocks | `(device_id, block_index)`; `(device_id, ts DESC)` | chain walk + recent |
| devices | `device_id` UNIQUE; `(status)`; `(health_state)` | lookup + fleet + ambient rollup |
| users | `email` UNIQUE | login |
| refresh_tokens | `(user_id)`; `(token_hash)` | rotation/lookup |
> Retention: raw `sensor_readings` 7 days high-res + `readings_1min` retained longer for `/analytics`.

## 05.6 Auth model & Row-Level Security
- **Roles:** `operator` (read own/assigned devices, ack alerts), `analyst` (+ledger, +analytics, +scenario inject), `admin` (all + user/device/config mgmt).
- **App-level scoping:** every device-scoped query filters by ownership/assignment for non-admins.
- **DB-level RLS (defense in depth):** enable on `devices`, `sensor_readings`, `decisions`, `alerts`, `ledger_blocks`.
  ```sql
  CREATE POLICY device_read ON devices FOR SELECT
    USING (current_setting('app.role')='admin'
           OR owner_user_id = current_setting('app.user_id')::uuid);
  CREATE POLICY readings_read ON sensor_readings FOR SELECT
    USING (current_setting('app.role')='admin'
           OR device_id IN (SELECT id FROM devices
                            WHERE owner_user_id = current_setting('app.user_id')::uuid));
  ```
- **Write protection:** config/threshold → admin only (API + RLS); scenario inject → analyst/admin; both write `audit_log` + `ledger_blocks`.
- **Tokens:** JWT access (`sub`,`role`); rotating revocable refresh; bcrypt passwords (cost from env).

## 05.7 REST API (core endpoints)
| Method | Path | Role | Purpose |
|--------|------|------|---------|
| POST | `/api/auth/login` | public | → access+refresh |
| POST | `/api/auth/refresh` | public(valid refresh) | rotate |
| POST | `/api/auth/logout` | auth | revoke refresh |
| GET | `/api/devices` | all | list (scoped) — includes `health_state` for Aurora |
| POST | `/api/devices` | admin | register |
| GET | `/api/devices/:id` | all(scoped) | detail |
| PATCH | `/api/devices/:id` | admin | edit |
| GET | `/api/devices/:id/readings?from&to&agg` | all(scoped) | history (uses aggregates) |
| GET | `/api/devices/:id/decisions?from&to` | all(scoped) | decision history |
| POST | `/api/devices/:id/inject` | analyst,admin | scenario injection → MQTT command |
| GET | `/api/alerts?device&status` | all(scoped) | list |
| POST | `/api/alerts/:id/ack` | all(scoped) | acknowledge |
| GET | `/api/ledger/:device_id` | analyst,admin | blocks |
| POST | `/api/ledger/:device_id/verify` | analyst,admin | integrity → {valid, broken_at?} |
| GET | `/api/ledger/:device_id/export` | analyst,admin | CSV/JSON |
| GET/PATCH | `/api/devices/:id/thresholds` | admin | config |
| GET/POST/PATCH | `/api/users` | admin | user mgmt |
| GET | `/api/system/health` | admin | mqtt/ws/db/latency |

## 05.8 WebSocket events (server→client, one multiplexed connection)
```jsonc
// connect: wss://…/ws?token=<jwt>&device_id=<id>   (token validated, device scoped)
{ "type":"telemetry", "device_id":"…", "ts":"…", "sensors":{ "temperature":…, "vibration":…, "pressure":…, "humidity":…, "gas":…, "current":… }, "sample_seq":123 }
{ "type":"decision", "device_id":"…", "ts":"…", "anomaly":{ "flag":true,"severity":0.82,"attribution":"attack","reason":"pressure vs current" }, "trust":{ "temperature":0.95,"…":"…","pressure":0.21 }, "health":"warning", "failure_eta":142, "rl_action":"isolate", "isolated":["pressure"], "substituted":["pressure"] }
{ "type":"ledger", "device_id":"…", "block_index":57, "ts":"…", "event":"isolate", "this_hash":"a1b2…9f0c", "prev_hash":"…" }
{ "type":"device_status", "device_id":"…", "status":"online|offline|degraded", "last_seen":"…" }
{ "type":"system_health", "device_id":"…", "health":"healthy|warning|critical", "mqtt":"connected", "ws_clients":3, "sample_rate_hz":1, "e2e_latency_ms":740 }   // drives Ambient Health Field
{ "type":"alert", "device_id":"…", "severity":"critical", "kind":"attack", "channel":"pressure", "message":"…", "reason":"…" }
```
**Client→server (control) go via REST** (`/inject`, `/ack`) not WS, so all mutations are auth-checked and audited uniformly. The `system_health.health` field is the single value the frontend maps to the Aurora background mood.

---

### Schema intent, in one line
One Postgres+TimescaleDB instance holds users, devices, six-channel telemetry, disambiguated decisions, per-sensor trust, a tamper-evident ledger, and RBAC/RLS — with a lightweight denormalized health rollup that lets the Aurora interface breathe in real time without ever touching the safety-critical edge logic.
