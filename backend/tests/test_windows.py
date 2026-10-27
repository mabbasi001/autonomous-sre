import uuid

import pytest
from sim_agent import SimAgent
from sqlalchemy import select
from test_enrollment import make_token

from app.detection.engine import process_pending_events
from app.incidents.manager import process_new_alerts
from app.models import Alert, Incident
from app.policies.catalogue import CATALOGUE
from app.policies.engine import Proposal, decide


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


def win_service(state: str) -> dict:
    return {
        "type": "windows.service",
        "payload": {"unit": "W3SVC", "active_state": state, "run_state": state.upper()},
    }


def app_pool(state: str) -> dict:
    return {
        "type": "iis.app_pool",
        "payload": {"pool": "DefaultAppPool", "active_state": state, "mgmt_state": state},
    }


def alerts(db, rule_name):
    return db.scalars(select(Alert).where(Alert.rule_name == rule_name)).all()


def test_windows_service_down_opens_incident(sim, db):
    sim.send("/v1/events", [win_service("inactive")])
    process_pending_events(db)
    process_new_alerts(db)

    fired = alerts(db, "windows-service-down")
    assert len(fired) == 1
    assert fired[0].fingerprint == f"winservice:W3SVC:{sim.agent_id}"
    incident = db.scalar(select(Incident))
    assert "windows-service-down" in incident.title

    # recovery resolves
    sim.send("/v1/events", [win_service("active")])
    process_pending_events(db)
    assert alerts(db, "windows-service-down")[0].status == "resolved"


def test_iis_app_pool_stopped_fires(sim, db):
    sim.send("/v1/events", [app_pool("inactive")])
    process_pending_events(db)
    process_new_alerts(db)

    fired = alerts(db, "iis-app-pool-stopped")
    assert len(fired) == 1
    assert fired[0].fingerprint == f"iis:DefaultAppPool:{sim.agent_id}"


def test_iis_recycle_is_in_catalogue_and_policy_governable(sim, db, client):
    assert "iis.recycle_app_pool" in CATALOGUE

    resp = client.post(
        "/v1/policies",
        json={
            "name": "iis-recycle",
            "environment": "development",
            "action": "iis.recycle_app_pool",
            "allowed_targets": ["DefaultAppPool"],
            "mode": "approval",
            "cooldown_seconds": 0,
            "rate_limit": {"max": 10, "window_seconds": 3600},
        },
    )
    assert resp.status_code == 201

    allowed = decide(
        db,
        Proposal(
            action="iis.recycle_app_pool",
            target="DefaultAppPool",
            agent_id=uuid.UUID(sim.agent_id),
            environment="development",
        ),
    )
    assert allowed.outcome == "approval_required"

    denied = decide(
        db,
        Proposal(
            action="iis.recycle_app_pool",
            target="OtherPool",
            agent_id=uuid.UUID(sim.agent_id),
            environment="development",
        ),
    )
    assert denied.outcome == "deny"


def test_bad_action_still_denied(sim, db):
    decision = decide(
        db,
        Proposal(
            action="iis.delete_site",
            target="x",
            agent_id=uuid.UUID(sim.agent_id),
            environment="development",
        ),
    )
    assert decision.outcome == "deny"
    assert "not in catalogue" in decision.reason


def test_windows_rules_are_seeded(client):
    rules = {r["name"]: r for r in client.get("/v1/alert-rules").json()["rules"]}
    assert "windows-service-down" in rules
    assert "iis-app-pool-stopped" in rules
    assert rules["windows-service-down"]["condition"]["event_type"] == "windows.service"


def test_operator_sets_windows_agent_config(sim, db, client):
    import json
    import tempfile

    cfg = {
        "collect_interval_seconds": 5,
        "services": ["W3SVC"],
        "iis_app_pools": ["DefaultAppPool"],
        "http_checks": [{"name": "site", "url": "http://localhost/"}],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
        path = f.name
    from app.cli import set_agent_config

    set_agent_config(sim.agent_id, path)
    served = sim.signed_get("/v1/agents/config").json()
    assert served["config"]["iis_app_pools"] == ["DefaultAppPool"]
