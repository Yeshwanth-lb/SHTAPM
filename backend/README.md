# backend/ — FastAPI service (WIRED-EMPTY in P0)

Read/observe + advisory-control plane only (**D003**): MQTT subscriber →
TimescaleDB/Postgres → WebSocket fan-out + REST. **Never** in the safety path.

Structure (TRD §02.6): `app/{api,ws,mqtt,models,schemas,core,services}`,
`alembic/`, `tests/`.

**P0 status:** package skeleton + placeholder `Dockerfile` only. The FastAPI
app, MQTT subscriber, WebSocket gateway, REST endpoints, ledger verifier, and
auth/RBAC/RLS are implemented in **P4** (with the DB schema per Doc05, which
is an early cross-cutting prerequisite — see project-state). Dependencies are
pinned in P4; `requirements.txt` is intentionally empty for now.

The `backend` compose service is gated behind the `app` profile so a default
`docker compose up` does not start a service that has no application yet.
