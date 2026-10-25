import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sim_agent import SimAgent
from sqlalchemy import select
from test_enrollment import make_token

from app.commands.service import execute_remediation, expire_commands
from app.config import settings
from app.detection.engine import process_pending_events
from app.incidents.manager import process_new_alerts, transition
from app.models import Command, Incident, IncidentEvidence, Verification
from app.security import sign
from app.verification import service
from app.verification.service import run_verifications


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


@pytest.fixture(autouse=True)
def fast_verification(monkeypatch):
    monkeypatch.setattr(settings, "verify_settle_seconds", 0)
    monkeypatch.setattr(service, "probe_url", lambda url: "unreachable")


def verifying_incident(sim, db):
    """Full path to VERIFYING: incident -> proposal -> dispatch -> success."""
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
        transition(db, incident, status, actor_type="system", reason="walk")
    execute_remediation(db, incident, "service.restart", "nginx", {"unit": "nginx"})
    respond_to_commands(sim, db, {"service.restart": agent_success("restarted")})
    db.refresh(incident)
    assert incident.status == "VERIFYING"
    return incident


def agent_success(output):
    return {"status": "succeeded", "exit_status": 0, "output": output}


def agent_failure(output, code=1):
    return {"status": "failed", "exit_status": code, "output": output, "error": "check failed"}


def respond_to_commands(sim, db, responses: dict) -> list[str]:
    """Agent-side: answer pending commands by action name."""
    answered = []
    listed = sim.signed_get("/v1/agents/commands").json()["commands"]
    for command in listed:
        payload = responses.get(command["action"])
        if payload is None:
            continue
        sim.signed_post(f"/v1/agents/commands/{command['id']}/ack", {})
        body = json.dumps(payload).encode()
        path = f"/v1/agents/commands/{command['id']}/result"
        ts = str(int(time.time()))
        sim.client.post(
            path,
            content=body,
            headers={
                "content-type": "application/json",
                "x-agent-id": sim.agent_id,
                "x-timestamp": ts,
                "x-signature": sign(sim.secret, "POST", path, ts, body),
            },
        )
        answered.append(command["action"])
    return answered


def set_http_check(db, sim, url="http://127.0.0.1:8000/healthz"):
    from app.models import AgentConfig

    db.add(
        AgentConfig(
            agent_id=uuid.UUID(sim.agent_id),
            version=1,
            config={"http_checks": [{"name": "web", "url": url}]},
        )
    )
    db.commit()


def test_all_checks_pass_resolves(sim, db, monkeypatch):
    from app.notifications import service as notif
    sent = []
    monkeypatch.setattr(settings, "slack_webhook_url", "http://hook.test/x")
    monkeypatch.setattr(notif, "post_webhook", lambda url, payload: sent.append(payload) or None)

    incident = verifying_incident(sim, db)
    run_verifications(db)  # creates round + dispatches (settle 0)
    answered = respond_to_commands(
        sim, db, {"service.status": agent_success("ActiveState=active\nSubState=running")}
    )
    assert answered == ["service.status"]
    run_verifications(db)

    db.refresh(incident)
    assert incident.status == "RESOLVED"
    verification = db.scalar(select(Verification))
    assert verification.status == "passed"
    assert verification.checks[0]["outcome"] == "pass"
    evidence = db.scalar(select(IncidentEvidence).where(IncidentEvidence.kind == "verification"))
    assert evidence.summary["status"] == "passed"
    notif.deliver_pending(db)
    assert any("resolved" in p["text"] for p in sent)


def test_failed_service_check_escalates(sim, db, monkeypatch):
    monkeypatch.setattr(settings, "verify_max_attempts", 1)
    incident = verifying_incident(sim, db)
    run_verifications(db)
    respond_to_commands(
        sim, db, {"service.status": agent_success("ActiveState=failed\nSubState=dead")}
    )
    run_verifications(db)

    db.refresh(incident)
    assert incident.status == "ESCALATED"
    assert db.scalar(select(Verification)).status == "failed"


def test_partial_recovery_mitigated(sim, db, monkeypatch):
    monkeypatch.setattr(settings, "verify_max_attempts", 1)
    incident = verifying_incident(sim, db)
    set_http_check(db, sim)
    run_verifications(db)
    respond_to_commands(
        sim,
        db,
        {
            "service.status": agent_success("ActiveState=active\nSubState=running"),
            "http.check": agent_failure("status_code=502", code=502),
        },
    )
    run_verifications(db)

    db.refresh(incident)
    assert incident.status == "MITIGATED"
    assert db.scalar(select(Verification)).status == "partial"


def test_agent_dark_escalates_never_resolves(sim, db):
    incident = verifying_incident(sim, db)
    run_verifications(db)

    # no responses at all: decision must wait, not resolve
    run_verifications(db)
    db.refresh(incident)
    assert incident.status == "VERIFYING"

    for command in db.scalars(
        select(Command).where(Command.status.in_(("pending", "delivered")))
    ).all():
        command.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    expire_commands(db)
    run_verifications(db)

    db.refresh(incident)
    assert incident.status == "ESCALATED"
    assert db.scalar(select(Verification)).status == "unreachable"


def test_retry_round_then_pass(sim, db, monkeypatch):
    monkeypatch.setattr(settings, "verify_max_attempts", 2)
    incident = verifying_incident(sim, db)
    run_verifications(db)
    respond_to_commands(
        sim, db, {"service.status": agent_success("ActiveState=activating\nSubState=start")}
    )
    run_verifications(db)  # round 1 fails -> round 2 scheduled
    db.refresh(incident)
    assert incident.status == "VERIFYING"

    run_verifications(db)  # dispatch round 2
    respond_to_commands(
        sim, db, {"service.status": agent_success("ActiveState=active\nSubState=running")}
    )
    run_verifications(db)

    db.refresh(incident)
    assert incident.status == "RESOLVED"
    rounds = db.scalars(select(Verification).order_by(Verification.attempt)).all()
    assert [r.status for r in rounds] == ["failed", "passed"]


def test_kill_switch_does_not_block_verification(sim, db, client):
    incident = verifying_incident(sim, db)
    client.put("/v1/kill-switches/global", json={"engaged": True, "reason": "freeze"})
    run_verifications(db)

    commands = sim.signed_get("/v1/agents/commands").json()["commands"]
    assert [c["action"] for c in commands] == ["service.status"]
    assert incident.status == "VERIFYING"


def test_central_probe_disagreement_fails_check(sim, db, monkeypatch):
    monkeypatch.setattr(settings, "verify_max_attempts", 1)
    monkeypatch.setattr(service, "probe_url", lambda url: "fail")
    incident = verifying_incident(sim, db)
    set_http_check(db, sim)
    run_verifications(db)
    respond_to_commands(
        sim,
        db,
        {
            "service.status": agent_success("ActiveState=active\nSubState=running"),
            "http.check": agent_success("status_code=200"),
        },
    )
    run_verifications(db)

    db.refresh(incident)
    assert incident.status == "MITIGATED"  # service passed, http disagreed
    verification = db.scalar(select(Verification))
    http = next(c for c in verification.checks if c["kind"] == "http.check")
    assert http["outcome"] == "fail"
    assert "central=fail" in http["detail"]