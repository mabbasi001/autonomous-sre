"""incidents, incident events and evidence

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("fingerprint", sa.String(256), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column(
            "environment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("environments.id"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_incidents_fingerprint_status", "incidents", ["fingerprint", "status"])

    op.create_table(
        "incident_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.id"), nullable=False
        ),
        sa.Column("event_id", UUID(as_uuid=True), sa.ForeignKey("events.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("incident_id", "event_id"),
    )

    op.create_table(
        "incident_evidence",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.id"), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("ref", sa.String(64), nullable=False),
        sa.Column("summary", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.add_column(
        "alerts",
        sa.Column(
            "incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.id"), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("alerts", "incident_id")
    op.drop_table("incident_evidence")
    op.drop_table("incident_events")
    op.drop_index("ix_incidents_fingerprint_status", table_name="incidents")
    op.drop_table("incidents")
