import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import operator_token
from sim_agent import SimAgent
from sqlalchemy import select
from test_enrollment import make_token

from app.commands.service import dispatch, execute_remediation, expire_commands
from app.detection.engine import process_pending_events
from app.incidents.manager import process_new_alerts, transition
from app.models import ActionExecution, AuditLog, Command, Incident, RemediationRun
from app.policies.engine import Proposal, decide
from app.security import sign


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


def proposed_incident(sim, db):
    sim.send(
        "/v1/events",
        [
            {
                "type": "systemd.service",
                "payload": {
                    "unit": "nginx",
                    "active_state": "inactive",
                    "sub_state": "x",
                    "restarts": 0,
                },
            }
        ],
    )
    process_pending_events(db)
    process_new_alerts(db)
    incident = db.scalar(select(Incident))
    for status in ("INVESTIGATING", "MANUAL_TRIAGE", "REMEDIATION_PROPOSED"):
        transition(db, incident, status, actor_type="system", reason="test walk")
    db.commit()
    return incident


def test_auto_policy_dispatches_command(sim, db):
    incident = proposed_incident(sim, db)
    decision = execute_remediation(
        db, incident, "service.restart", "nginx", {"unit": "nginx"}
    )
    assert decision.outcome == "allow"

    db.refresh(incident)
    assert incident.status == "EXECUTING"
    command = db.scalar(select(Command))
    assert command.status == "pending"
    assert command.action == "service.restart"
    assert command.params == {"unit": "nginx"}
    assert command.idempotency_key
    assert command.expires_at > datetime.now(UTC) - timedelta(seconds=5)
    run = db.scalar(select(RemediationRun))
    assert run.status == "running" and run.target == "nginx"


def test_kill_switch_blocks_at_dispatch_time(sim, db, client):
    incident = proposed_incident(sim, db)
    decision = decide(
        db,
        Proposal(
            action="service.restart",
            target="nginx",
            agent_id=uuid.UUID(sim.agent_id),
            environment="development",
            incident_id=incident.id,
        ),
    )
    assert decision.outcome == "allow"

    client.put("/v1/kill-switches/global", json={"engaged": True, "reason": "freeze"})
    command = dispatch(db, incident, decision, {"unit": "nginx"})

    assert command is None
    assert db.scalar(select(Command)) is None
    db.refresh(incident)
    assert incident.status == "ESCALATED"
    assert db.scalar(select(AuditLog).where(AuditLog.event_type == "command.blocked"))


def test_approved_approval_dispatches(sim, db, client):
    client.post(
        "/v1/policies",
        json={
            "name": "payments-restart",
            "environment": "development",
            "action": "service.restart",
            "allowed_targets": ["payments"],
            "mode": "approval",
            "cooldown_seconds": 0,
            "rate_limit": {"max": 100, "window_seconds": 3600},
        },
    )
    incident = proposed_incident(sim, db)
    decision = execute_remediation(
        db, incident, "service.restart", "payments", {"unit": "payments"}
    )
    assert decision.outcome == "approval_required"
    assert db.scalar(select(Command)) is None

    approvals = client.get("/v1/approvals?status=pending").json()["approvals"]
    resp = client.post(
        f"/v1/approvals/{approvals[0]['id']}/decision",
        json={"decision": "approved", "reason": "go ahead"},
        headers={"Authorization": f"Bearer {operator_token('approver')}"},
    )
    assert resp.status_code == 200

    db.expire_all()
    command = db.scalar(select(Command))
    assert command is not None
    assert command.params == {"unit": "payments"}
    assert db.get(Incident, incident.id).status == "EXECUTING"


def test_denied_proposal_escalates(sim, db):
    incident = proposed_incident(sim, db)
    decision = execute_remediation(db, incident, "service.restart", "redis", {"unit": "redis"})
    assert decision.outcome == "deny"
    db.refresh(incident)
    assert incident.status == "ESCALATED"
    assert db.scalar(select(Command)) is None


def agent_result(sim, command_id, payload):
    body = json.dumps(payload).encode()
    path = f"/v1/agents/commands/{command_id}/result"
    ts = str(int(time.time()))
    return sim.client.post(
        path,
        content=body,
        headers={
            "content-type": "application/json",
            "x-agent-id": sim.agent_id,
            "x-timestamp": ts,
            "x-signature": sign(sim.secret, "POST", path, ts, body),
        },
    )


def agent_ack(sim, command_id):
    return sim.signed_post(f"/v1/agents/commands/{command_id}/ack", {})


def test_agent_poll_ack_result_success(sim, db):
    incident = proposed_incident(sim, db)
    execute_remediation(db, incident, "service.restart", "nginx", {"unit": "nginx"})

    listed = sim.signed_get("/v1/agents/commands").json()["commands"]
    assert len(listed) == 1
    command_id = listed[0]["id"]
    assert listed[0]["action"] == "service.restart"

    assert agent_ack(sim, command_id).status_code == 200
    resp = agent_result(
        sim,
        command_id,
        {"status": "succeeded", "exit_status": 0, "output": "restarted", "duration_ms": 420},
    )
    assert resp.status_code == 200

    db.expire_all()
    command = db.get(Command, uuid.UUID(command_id))
    assert command.status == "succeeded"
    execution = db.scalar(select(ActionExecution))
    assert execution.exit_status == 0 and execution.output == "restarted"
    assert db.get(Incident, incident.id).status == "VERIFYING"
    assert sim.signed_get("/v1/agents/commands").json()["commands"] == []


def test_failed_result_escalates(sim, db):
    incident = proposed_incident(sim, db)
    execute_remediation(db, incident, "service.restart", "nginx", {"unit": "nginx"})
    command_id = sim.signed_get("/v1/agents/commands").json()["commands"][0]["id"]
    agent_ack(sim, command_id)
    agent_result(sim, command_id, {"status": "failed", "exit_status": 1, "error": "unit not found"})

    db.expire_all()
    assert db.get(Incident, incident.id).status == "ESCALATED"
    assert db.scalar(select(RemediationRun)).status == "failed"


def test_expired_command_rejected_and_escalates(sim, db):
    incident = proposed_incident(sim, db)
    execute_remediation(db, incident, "service.restart", "nginx", {"unit": "nginx"})
    command = db.scalar(select(Command))
    command.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert agent_ack(sim, str(command.id)).status_code == 409
    db.expire_all()
    assert db.get(Command, command.id).status == "expired"
    assert db.get(Incident, incident.id).status == "ESCALATED"

    late = agent_result(sim, str(command.id), {"status": "succeeded"})
    assert late.status_code == 409


def test_expiry_sweep(sim, db):
    incident = proposed_incident(sim, db)
    execute_remediation(db, incident, "service.restart", "nginx", {"unit": "nginx"})
    command = db.scalar(select(Command))
    command.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert expire_commands(db) == 1
    db.expire_all()
    assert db.get(Command, command.id).status == "expired"
    assert db.scalar(select(RemediationRun)).status == "expired"
    assert db.get(Incident, incident.id).status == "ESCALATED"


def test_commands_scoped_to_owning_agent(sim, db, client):
    incident = proposed_incident(sim, db)
    execute_remediation(db, incident, "service.restart", "nginx", {"unit": "nginx"})
    command_id = sim.signed_get("/v1/agents/commands").json()["commands"][0]["id"]

    other = SimAgent(client, hostname="other-agent")
    other.enroll(make_token(db))
    assert other.signed_get("/v1/agents/commands").json()["commands"] == []
    assert other.signed_post(f"/v1/agents/commands/{command_id}/ack", {}).status_code == 404


def test_duplicate_result_rejected(sim, db):
    incident = proposed_incident(sim, db)
    execute_remediation(db, incident, "service.restart", "nginx", {"unit": "nginx"})
    command_id = sim.signed_get("/v1/agents/commands").json()["commands"][0]["id"]
    agent_ack(sim, command_id)
    assert agent_result(sim, command_id, {"status": "succeeded"}).status_code == 200
    assert agent_result(sim, command_id, {"status": "failed"}).status_code == 409