"""schema v0: environments, users, agents

Revision ID: 0001
Revises:
Create Date: 2026-10-31

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "environment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("environments.id"),
            nullable=False,
        ),
        sa.Column("hostname", sa.String(253), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute(
        "INSERT INTO environments (id, name) VALUES "
        "(gen_random_uuid(), 'development'), "
        "(gen_random_uuid(), 'staging'), "
        "(gen_random_uuid(), 'production')"
    )


def downgrade() -> None:
    op.drop_table("agents")
    op.drop_table("users")
    op.drop_table("environments")
