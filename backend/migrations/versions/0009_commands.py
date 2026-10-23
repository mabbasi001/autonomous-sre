"""commands, remediation runs and action executions

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approvals",
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "commands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column(
            "incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.id"), nullable=True
        ),
        sa.Column(
            "policy_decision_id",
            UUID(as_uuid=True),
            sa.ForeignKey("policy_decisions.id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_commands_agent_status", "commands", ["agent_id", "status"])

    op.create_table(
        "remediation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.id"), nullable=False
        ),
        sa.Column("command_id", UUID(as_uuid=True), sa.ForeignKey("commands.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "action_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("command_id", UUID(as_uuid=True), sa.ForeignKey("commands.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("exit_status", sa.Integer(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("action_executions")
    op.drop_table("remediation_runs")
    op.drop_index("ix_commands_agent_status", table_name="commands")
    op.drop_table("commands")
    op.drop_column("approvals", "params")
