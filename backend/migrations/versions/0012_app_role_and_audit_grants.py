"""application role with append-only audit access

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01

"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # the runtime role; migrations keep running as the owning role
    op.execute(
        """
        DO $$ BEGIN
            CREATE ROLE sre_app LOGIN PASSWORD 'sre_app';
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        "DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO sre_app',"
        " current_database()); END $$;"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO sre_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sre_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public"
        " GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sre_app"
    )
    # the audit trail is append-only for the application
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM sre_app")


def downgrade() -> None:
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM sre_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public"
        " REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM sre_app"
    )
