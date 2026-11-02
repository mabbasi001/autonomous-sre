"""generic systemd service-down rule (any unit, not just nginx)

Replaces the nginx-pinned Linux rule with a generic one that fires for
any watched systemd unit, mirroring the already-generic
``windows-service-down`` rule. The collector already emits an event per
configured unit; only the rule was service-specific.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-02

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_rules = sa.table(
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

GENERIC_RULE = {
    "name": "systemd-service-down",
    "rule_type": "state_change",
    "severity": "high",
    "condition": {
        "event_type": "systemd.service",
        "identity_fields": ["unit"],
        "field": "active_state",
        "bad_values": ["inactive", "failed"],
    },
    "fingerprint_template": "systemd:{unit}:{agent_id}",
}

NGINX_RULE = {
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
}


def _insert(rule: dict) -> None:
    op.bulk_insert(
        _rules, [{"id": uuid.uuid4(), "version": 1, "scope": {}, "enabled": True, **rule}]
    )


def upgrade() -> None:
    _insert(GENERIC_RULE)
    # Remove the nginx-specific rule so nginx isn't matched twice (the
    # generic rule now covers it, with the same fingerprint).
    op.execute("DELETE FROM alert_rules WHERE name = 'nginx-service-down'")


def downgrade() -> None:
    op.execute("DELETE FROM alert_rules WHERE name = 'systemd-service-down'")
    _insert(NGINX_RULE)
