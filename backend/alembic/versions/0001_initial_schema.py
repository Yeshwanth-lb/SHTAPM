"""Initial schema — all Doc05 §05.2 tables + TimescaleDB hypertables.

Postgres/TimescaleDB only (matches the running ``docker-compose.yml`` `db`
service, ``timescale/timescaledb:2.14.2-pg16``). Column shapes mirror
``backend/app/models/*`` exactly, but this migration uses native
``postgresql.JSONB``/``postgresql.ENUM`` (letter-perfect Doc05) where the ORM
models use portable generic ``JSON``/``Enum`` types for SQLite-testability —
both interoperate against the same real Postgres columns (see
``backend/app/models/decision.py`` docstring).

Enum types are created explicitly once (``create_type=False`` on every column
use) because ``op.create_table`` does not share the automatic per-``MetaData``
enum-dedup that ``Base.metadata.create_all()`` gets for free.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---- enum type definitions (Doc05 §05.2 value sets) -----------------------
user_role = postgresql.ENUM("operator", "analyst", "admin", name="user_role", create_type=False)
device_status = postgresql.ENUM(
    "online", "offline", "degraded", name="device_status", create_type=False
)
health_state = postgresql.ENUM(
    "healthy", "warning", "critical", name="health_state", create_type=False
)
channel = postgresql.ENUM(
    "temperature", "vibration", "pressure", "humidity", "gas", "current",
    name="channel", create_type=False,
)
attribution = postgresql.ENUM("none", "fault", "attack", name="attribution", create_type=False)
rl_action = postgresql.ENUM(
    "continue", "reduce_weight", "isolate", "alert", "safe_stop",
    name="rl_action", create_type=False,
)
alert_severity = postgresql.ENUM(
    "info", "warning", "critical", name="alert_severity", create_type=False
)
alert_type = postgresql.ENUM("fault", "attack", "system", name="alert_type", create_type=False)

_ALL_ENUMS = (
    user_role, device_status, health_state, channel, attribution,
    rl_action, alert_severity, alert_type,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ALL_ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", device_status, nullable=False, server_default="offline"),
        sa.Column("health_state", health_state, nullable=False, server_default="healthy"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample_rate_hz", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_devices_device_id", "devices", ["device_id"])
    op.create_index("ix_devices_status", "devices", ["status"])
    op.create_index("ix_devices_health_state", "devices", ["health_state"])

    op.create_table(
        "sensors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("channel", channel, nullable=False),
        sa.Column("part", sa.String(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("is_proxy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_hue", sa.String(), nullable=True),
        sa.UniqueConstraint("device_id", "channel", name="uq_sensors_device_channel"),
    )

    op.create_table(
        "sensor_readings",
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id"), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("sample_seq", sa.BigInteger(), primary_key=True),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("vibration", sa.Float(), nullable=False),
        sa.Column("pressure", sa.Float(), nullable=False),
        sa.Column("humidity", sa.Float(), nullable=False),
        sa.Column("gas", sa.Float(), nullable=False),
        sa.Column("current", sa.Float(), nullable=False),
        sa.Column("healthy_mask", sa.Integer(), nullable=False),
    )
    op.create_index("ix_sensor_readings_device_ts", "sensor_readings", ["device_id", "ts"])

    op.create_table(
        "decisions",
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id"), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("anomaly_flag", sa.Boolean(), nullable=True),
        sa.Column("anomaly_severity", sa.Float(), nullable=True),
        sa.Column("attribution", attribution, nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("trust_temperature", sa.Float(), nullable=True),
        sa.Column("trust_vibration", sa.Float(), nullable=True),
        sa.Column("trust_pressure", sa.Float(), nullable=True),
        sa.Column("trust_humidity", sa.Float(), nullable=True),
        sa.Column("trust_gas", sa.Float(), nullable=True),
        sa.Column("trust_current", sa.Float(), nullable=True),
        sa.Column("health_state", health_state, nullable=True),
        sa.Column("failure_eta", sa.Float(), nullable=True),
        sa.Column("rl_action", rl_action, nullable=True),
        sa.Column("isolated_channels", postgresql.JSONB(), nullable=True),
        sa.Column("substituted_channels", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_decisions_device_ts", "decisions", ["device_id", "ts"])
    op.create_index(
        "ix_decisions_attack",
        "decisions",
        ["device_id", "ts"],
        postgresql_where=sa.text("attribution = 'attack'"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column("type", alert_type, nullable=False),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("acknowledged_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_device_ts", "alerts", ["device_id", "ts"])
    op.create_index(
        "ix_alerts_unacked",
        "alerts",
        ["acknowledged_at"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )

    op.create_table(
        "ledger_blocks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("block_index", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("prev_hash", sa.String(), nullable=False),
        sa.Column("this_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("device_id", "block_index", name="uq_ledger_blocks_device_index"),
    )
    op.create_index("ix_ledger_blocks_device_ts", "ledger_blocks", ["device_id", "ts"])

    op.create_table(
        "thresholds",
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id"), primary_key=True),
        sa.Column("trust_trusted_min", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("trust_malicious_max", sa.Float(), nullable=False, server_default="0.4"),
        sa.Column("trust_w_consistency", sa.Float(), nullable=False, server_default="0.4"),
        sa.Column("trust_w_correlation", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("trust_w_reliability", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("window_size", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("substitution_max_seconds", sa.Integer(), nullable=False, server_default="60"),
        # divergence_threshold: NO default — U05 still open, never silently defaulted.
        sa.Column("divergence_threshold", sa.Float(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    # ---- TimescaleDB hypertables (Doc05 §05.1) -----------------------------
    # Requires the timescaledb extension (present in the timescale/timescaledb
    # image used by docker-compose.yml's `db` service).
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute(
        "SELECT create_hypertable('sensor_readings', 'ts', if_not_exists => TRUE, "
        "migrate_data => TRUE)"
    )
    op.execute(
        "SELECT create_hypertable('decisions', 'ts', if_not_exists => TRUE, migrate_data => TRUE)"
    )


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("audit_log")
    op.drop_table("thresholds")
    op.drop_table("ledger_blocks")
    op.drop_table("alerts")
    op.drop_table("decisions")
    op.drop_table("sensor_readings")
    op.drop_table("sensors")
    op.drop_table("devices")
    op.drop_table("users")

    bind = op.get_bind()
    for enum_type in _ALL_ENUMS:
        enum_type.drop(bind, checkfirst=True)
