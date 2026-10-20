"""policies, policy decisions and kill switches

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(64), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("allowed_targets", JSONB, nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("rate_limit", JSONB, nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name", "version"),
    )

    op.create_table(
        "policy_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("environment", sa.String(64), nullable=False),
        sa.Column(
            "incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.id"), nullable=True
        ),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("policy_name", sa.String(128), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=True),
        sa.Column("inputs", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_policy_decisions_action_target",
        "policy_decisions",
        ["action", "target", "created_at"],
    )

    op.create_table(
        "kill_switches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(128), nullable=False, unique=True),
        sa.Column("engaged", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    policies = sa.table(
        "policies",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("version", sa.Integer),
        sa.column("environment", sa.String),
        sa.column("action", sa.String),
        sa.column("allowed_targets", JSONB),
        sa.column("mode", sa.String),
        sa.column("rate_limit", JSONB),
        sa.column("cooldown_seconds", sa.Integer),
        sa.column("max_retries", sa.Integer),
        sa.column("enabled", sa.Boolean),
    )
    # the vertical slice: nginx restarts may run automatically in development.
    # production gets no seeded policies - enabling remediation there is a
    # deliberate, reviewed act.
    op.bulk_insert(
        policies,
        [
            {
                "id": uuid.uuid4(),
                "name": "dev-service-restart",
                "version": 1,
                "environment": "development",
                "action": "service.restart",
                "allowed_targets": ["nginx"],
                "mode": "auto",
                "rate_limit": {"max": 3, "window_seconds": 3600},
                "cooldown_seconds": 300,
                "max_retries": 2,
                "enabled": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("kill_switches")
    op.drop_index("ix_policy_decisions_action_target", table_name="policy_decisions")
    op.drop_table("policy_decisions")
    op.drop_table("policies")
