"""alert rules, alerts, rule state and event processing cursor

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SEED_RULES = [
    {
        "name": "nginx-service-down",
        "rule_type": "state_change",
        "severity": "high",
        "condition": {
            "event_type": "systemd.service",
            "match": {"unit": "nginx"},
            "identity_fields": ["unit"],
            "field": "active_state",
            "bad_values": ["inactive", "failed"],
        },
        "fingerprint_template": "systemd:{unit}:{agent_id}",
    },
    {
        "name": "http-check-failing",
        "rule_type": "state_change",
        "severity": "high",
        "condition": {
            "event_type": "http.check",
            "identity_fields": ["name"],
            "field": "ok",
            "bad_values": [False],
        },
        "fingerprint_template": "http:{name}:{agent_id}",
    },
    {
        "name": "heartbeat-missing",
        "rule_type": "absence",
        "severity": "critical",
        "condition": {"max_silence_seconds": 90},
        "fingerprint_template": "heartbeat:{agent_id}",
    },
    {
        "name": "disk-usage-high",
        "rule_type": "threshold",
        "severity": "warning",
        "condition": {
            "metric": "host.disk_used_percent",
            "operator": ">",
            "threshold": 90,
            "duration_seconds": 300,
        },
        "fingerprint_template": "disk:{agent_id}",
    },
]


def upgrade() -> None:
    op.add_column("events", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_events_unprocessed",
        "events",
        ["created_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    op.create_table(
        "alert_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("scope", JSONB, nullable=False),
        sa.Column("condition", JSONB, nullable=False),
        sa.Column("fingerprint_template", sa.String(256), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name", "version"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_name", sa.String(128), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(256), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column(
            "environment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("environments.id"),
            nullable=False,
        ),
        sa.Column("event_ids", JSONB, nullable=False),
        sa.Column("context", JSONB, nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_alerts_fingerprint_status", "alerts", ["fingerprint", "status"])

    op.create_table(
        "rule_state",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_name", sa.String(128), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("state", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("rule_name", "agent_id", "key"),
    )

    rules = sa.table(
        "alert_rules",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("version", sa.Integer),
        sa.column("rule_type", sa.String),
        sa.column("severity", sa.String),
        sa.column("scope", JSONB),
        sa.column("condition", JSONB),
        sa.column("fingerprint_template", sa.String),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        rules,
        [
            {"id": uuid.uuid4(), "version": 1, "scope": {}, "enabled": True, **seed}
            for seed in SEED_RULES
        ],
    )


def downgrade() -> None:
    op.drop_table("rule_state")
    op.drop_index("ix_alerts_fingerprint_status", table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
    op.drop_index("ix_events_unprocessed", table_name="events")
    op.drop_column("events", "processed_at")
