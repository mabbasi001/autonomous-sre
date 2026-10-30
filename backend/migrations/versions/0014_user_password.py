"""local-account password hash on users

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-02

"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: Entra-provisioned users have no local password.
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
