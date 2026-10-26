import uuid

import pytest
from conftest import TEST_URL, operator_token
from sim_agent import SimAgent
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import ProgrammingError
from test_enrollment import make_token
from test_investigation import FakeProvider, diagnosis

from app.config import settings
from app.detection.engine import process_pending_events
from app.incidents.manager import process_new_alerts
from app.investigation.service import investigate
from app.models import Approval, AuditLog, Command, Incident
from app.security import sign
from app.verification import service as verif_service
from app.verification.service import run_verifications

APP_ROLE_URL = TEST_URL.replace("sre:sre@", "sre_app:sre_app@")


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


def test_app_role_cannot_modify_audit_logs(db, sim):
    sim.heartbeat()  # ensures at least one audit row exists
    engine = create_engine(APP_ROLE_URL)
    with engine.connect() as conn:
        count = conn.execute(text("select count(*) from audit_logs")).scalar()
        assert count >= 1  # SELECT allowed

        conn.execute(
            text(
                "insert into audit_logs (id, actor_type, event_type, created_at)"
                " values (:id, 'system', 'audit.test', now())"
            ),
            {"id": str(uuid.uuid4())},
        )  # INSERT allowed

        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("update audit_logs set actor_type = 'tampered'"))
        conn.rollback()
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("delete from audit_logs"))
        conn.rollback()
    engine.dispose()


def agent_result(sim, command_id, payload):
    import json
    import time

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


def test_full_remediation_chain_reconstructable(sim, db, client, monkeypatch):
    monkeypatch.setattr(settings, "verify_settle_seconds", 0)
    monkeypatch.setattr(verif_service, "probe_url", lambda url: "unreachable")
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

    investigate(db, incident, provider=FakeProvider(diagnosis(unit="payments")))
    db.refresh(incident)
    assert incident.status == "AWAITING_APPROVAL"

    approval = db.scalar(select(Approval))
    client.post(
        f"/v1/approvals/{approval.id}/decision",
        json={"decision": "approved", "reason": "restart approved for the chain test"},
        headers={"Authorization": f"Bearer {operator_token('approver')}"},
    )

    db.expire_all()
    command = db.scalar(select(Command).where(Command.action == "service.restart"))
    sim.signed_post(f"/v1/agents/commands/{command.id}/ack", {})
    agent_result(sim, str(command.id), {"status": "succeeded", "exit_status": 0})

    run_verifications(db)  # dispatch read-only check
    check = db.scalar(
        select(Command).where(Command.action == "service.status", Command.status == "pending")
    )
    sim.signed_post(f"/v1/agents/commands/{check.id}/ack", {})
    agent_result(
        sim,
        str(check.id),
        {"status": "succeeded", "exit_status": 0, "output": "ActiveState=active"},
    )
    db.expire_all()
    run_verifications(db)
    db.expire_all()
    assert db.get(Incident, incident.id).status == "RESOLVED"

    # one query over the involved entity ids reconstructs the whole story
    entity_ids = [str(incident.id), str(approval.id), str(command.id)]
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_id.in_(entity_ids))
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()
    seen = [row.event_type for row in rows]
    for expected in (
        "incident.opened",
        "investigation.completed",
        "policy.decision",
        "approval.requested",
        "approval.approved",
        "command.created",
        "command.succeeded",
        "verification.passed",
    ):
        assert expected in seen, f"{expected} missing from chain: {seen}"
    assert all(row.actor_type for row in rows)
    assert any(
        row.event_type == "incident.transition" and row.detail["to"] == "RESOLVED"
        for row in rows
    )
    approved = next(row for row in rows if row.event_type == "approval.approved")
    assert approved.actor_id == "approver@test.local"
    assert approved.detail["reason"] == "restart approved for the chain test"


def test_correlation_id_links_api_call_to_audit(db, client):
    client.put(
        "/v1/kill-switches/global",
        json={"engaged": True, "reason": "audit correlation check"},
        headers={"x-correlation-id": "corr-12345"},
    )
    row = db.scalar(select(AuditLog).where(AuditLog.event_type == "kill_switch.engaged"))
    assert row.correlation_id == "corr-12345"
    assert row.actor_id  # dev-admin or token user, never anonymous


def test_role_change_is_audited(db, anon_client):
    email = "mover@test.local"
    anon_client.get(
        "/v1/incidents",
        headers={"Authorization": f"Bearer {operator_token('viewer', email=email)}"},
    )
    anon_client.get(
        "/v1/incidents",
        headers={"Authorization": f"Bearer {operator_token('admin', email=email)}"},
    )
    row = db.scalar(select(AuditLog).where(AuditLog.event_type == "user.role_changed"))
    assert row.actor_id == email
    assert row.detail == {"from": "viewer", "to": "admin"}


def test_audit_api_filters_and_rbac(db, client, anon_client, sim):
    client.put("/v1/kill-switches/global", json={"engaged": True, "reason": "x"})
    client.put("/v1/kill-switches/global", json={"engaged": False, "reason": "y"})

    assert anon_client.get("/v1/audit-logs").status_code == 401

    viewer = {"Authorization": f"Bearer {operator_token('viewer')}"}
    body = anon_client.get(
        "/v1/audit-logs?event_type=kill_switch.engaged", headers=viewer
    ).json()
    assert len(body["audit_logs"]) == 1
    assert body["audit_logs"][0]["event_type"] == "kill_switch.engaged"

    limited = anon_client.get("/v1/audit-logs?limit=1", headers=viewer).json()
    assert len(limited["audit_logs"]) == 1