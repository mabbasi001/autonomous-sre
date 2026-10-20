import uuid
from datetime import UTC, datetime

import pytest
from sim_agent import SimAgent
from test_enrollment import make_token

from app.models import Agent, Incident
from app.policies.engine import Proposal, decide, kill_switch_engaged


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


def proposal(sim, **overrides) -> Proposal:
    defaults = {
        "action": "service.restart",
        "target": "nginx",
        "agent_id": uuid.UUID(sim.agent_id),
        "environment": "development",
    }
    return Proposal(**defaults | overrides)


def make_incident(db, sim, status="REMEDIATION_PROPOSED") -> Incident:
    agent = db.get(Agent, uuid.UUID(sim.agent_id))
    incident = Incident(
        fingerprint=f"test:{uuid.uuid4()}",
        title="test incident",
        status=status,
        severity="high",
        agent_id=agent.id,
        environment_id=agent.environment_id,
        opened_at=datetime.now(UTC),
    )
    db.add(incident)
    db.commit()
    return incident


def create_policy(client, **overrides):
    body = {
        "name": overrides.pop("name"),
        "environment": "development",
        "action": "service.restart",
        "allowed_targets": ["nginx"],
        "mode": "auto",
        "rate_limit": {"max": 100, "window_seconds": 3600},
        "cooldown_seconds": 0,
        "max_retries": 10,
    } | overrides
    resp = client.post("/v1/policies", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def engage(client, scope, engaged=True):
    resp = client.put(
        f"/v1/kill-switches/{scope}", json={"engaged": engaged, "reason": "test"}
    )
    assert resp.status_code == 200


def test_readonly_always_allowed_even_under_kill_switch(sim, db, client):
    engage(client, "global")
    decision = decide(db, proposal(sim, action="service.status"))
    assert decision.outcome == "allow"
    assert decision.reason == "read-only action"


def test_unknown_action_always_denied(sim, db, client):
    decision = decide(db, proposal(sim, action="vm.delete"))
    assert decision.outcome == "deny"
    assert "not in catalogue" in decision.reason

    engage(client, "global")
    decision = decide(db, proposal(sim, action="shell.exec"))
    assert decision.outcome == "deny"
    assert "not in catalogue" in decision.reason


def test_dev_restart_allowed_by_seeded_policy(sim, db):
    decision = decide(db, proposal(sim))
    assert decision.outcome == "allow"
    assert decision.policy_name == "dev-service-restart"
    assert decision.policy_version == 1


def test_prod_restart_requires_approval(sim, db, client):
    create_policy(
        client, name="prod-service-restart", environment="production", mode="approval"
    )
    decision = decide(db, proposal(sim, environment="production"))
    assert decision.outcome == "approval_required"
    assert decision.policy_name == "prod-service-restart"


def test_unlisted_target_denied(sim, db):
    decision = decide(db, proposal(sim, target="redis"))
    assert decision.outcome == "deny"
    assert "no enabled policy" in decision.reason


def test_cooldown_denies_immediate_second_restart(sim, db):
    assert decide(db, proposal(sim)).outcome == "allow"
    second = decide(db, proposal(sim))
    assert second.outcome == "deny"
    assert "cooldown" in second.reason


def test_rate_limit_denies_after_window_budget(sim, db, client):
    create_policy(
        client,
        name="rate-test",
        allowed_targets=["api"],
        rate_limit={"max": 2, "window_seconds": 3600},
    )
    assert decide(db, proposal(sim, target="api")).outcome == "allow"
    assert decide(db, proposal(sim, target="api")).outcome == "allow"
    third = decide(db, proposal(sim, target="api"))
    assert third.outcome == "deny"
    assert "rate limit" in third.reason


def test_retry_cap_per_incident(sim, db, client):
    create_policy(client, name="retry-test", allowed_targets=["worker"], max_retries=2)
    incident = make_incident(db, sim)

    p = proposal(sim, target="worker", incident_id=incident.id)
    assert decide(db, p).outcome == "allow"
    assert decide(db, p).outcome == "allow"
    third = decide(db, p)
    assert third.outcome == "deny"
    assert "retry limit" in third.reason


def test_closed_incident_denied(sim, db, client):
    create_policy(client, name="closed-test", allowed_targets=["cron"])
    incident = make_incident(db, sim, status="CLOSED")

    decision = decide(db, proposal(sim, target="cron", incident_id=incident.id))
    assert decision.outcome == "deny"
    assert "CLOSED" in decision.reason


def test_kill_switch_denies_at_proposal_and_dispatch(sim, db, client):
    engage(client, "environment:development")
    decision = decide(db, proposal(sim))
    assert decision.outcome == "deny"
    assert "kill switch" in decision.reason
    assert kill_switch_engaged(db, "development") == "environment:development"

    engage(client, "environment:development", engaged=False)
    assert kill_switch_engaged(db, "development") is None
    assert decide(db, proposal(sim)).outcome == "allow"

    engage(client, "global")
    assert kill_switch_engaged(db, "development") == "global"


def test_decision_rows_are_reproducible(sim, db):
    decision = decide(db, proposal(sim))
    assert decision.outcome == "allow"
    assert decision.policy_version == 1
    assert decision.inputs["risk"] == "low"
    assert decision.inputs["kill_switch"] is None
    assert decision.inputs["recent_count"] == 0
    assert decision.inputs["evaluated_at"]
    assert decision.action == "service.restart" and decision.target == "nginx"


def test_policy_edit_versions_and_old_decisions_keep(sim, db, client):
    create_policy(client, name="edit-test", allowed_targets=["svc-x"])
    first = decide(db, proposal(sim, target="svc-x"))
    assert first.outcome == "allow" and first.policy_version == 1

    create_policy(client, name="edit-test", allowed_targets=["svc-x"], mode="approval")
    listed = {p["name"]: p for p in client.get("/v1/policies").json()["policies"]}
    assert listed["edit-test"]["version"] == 2

    second = decide(db, proposal(sim, target="svc-x"))
    assert second.outcome == "approval_required" and second.policy_version == 2

    db.refresh(first)
    assert first.policy_version == 1


def test_policy_validation(client):
    resp = client.post(
        "/v1/policies",
        json={
            "name": "bad",
            "action": "vm.delete",
            "allowed_targets": ["x"],
            "mode": "auto",
        },
    )
    assert resp.status_code == 422

    resp = client.put("/v1/kill-switches/environment:nope", json={"engaged": True, "reason": "x"})
    assert resp.status_code == 422