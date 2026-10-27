"""windows service and iis app pool alert rules

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-01

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

RULES = [
    {
        "name": "windows-service-down",
        "rule_type": "state_change",
        "severity": "high",
        "condition": {
            "event_type": "windows.service",
            "identity_fields": ["unit"],
            "field": "active_state",
            "bad_values": ["inactive", "failed"],
        },
        "fingerprint_template": "winservice:{unit}:{agent_id}",
    },
    {
        "name": "iis-app-pool-stopped",
        "rule_type": "state_change",
        "severity": "high",
        "condition": {
            "event_type": "iis.app_pool",
            "identity_fields": ["pool"],
            "field": "active_state",
            "bad_values": ["inactive"],
        },
        "fingerprint_template": "iis:{pool}:{agent_id}",
    },
]


def upgrade() -> None:
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
            {"id": uuid.uuid4(), "version": 1, "scope": {}, "enabled": True, **rule}
            for rule in RULES
        ],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM alert_rules WHERE name IN ('windows-service-down', 'iis-app-pool-stopped')"
    )
