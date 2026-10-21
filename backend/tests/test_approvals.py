import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import operator_token
from sim_agent import SimAgent
from sqlalchemy import select, text
from test_enrollment import make_token

from app.approvals.service import expire_pending, request_approval
from app.config import settings
from app.detection.engine import process_pending_events
from app.incidents.manager import process_new_alerts, transition
from app.models import AuditLog, Incident, Notification
from app.notifications import service as notif_service
from app.policies.engine import Proposal, decide


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


@pytest.fixture()
def hook(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "slack_webhook_url", "http://hook.test/webhook")
    monkeypatch.setattr(
        notif_service, "post_webhook", lambda url, payload: calls.append(payload) or None
    )
    return calls


def bearer(role, email=None):
    return {"Authorization": f"Bearer {operator_token(role, email=email)}"}


@pytest.fixture()
def pending(sim, db, client):
    """An incident in AWAITING_APPROVAL with a pending approval."""
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
    for status in ("INVESTIGATING", "MANUAL_TRIAGE", "REMEDIATION_PROPOSED"):
        transition(db, incident, status, actor_type="system", reason="test walk")

    decision = decide(
        db,
        Proposal(
            action="service.restart",
            target="payments",
            agent_id=uuid.UUID(sim.agent_id),
            environment="development",
            incident_id=incident.id,
        ),
    )
    assert decision.outcome == "approval_required"
    approval = request_approval(db, incident, decision)
    db.commit()
    return approval


def test_request_moves_incident_to_awaiting_and_notifies(hook, pending, db):
    incident = db.get(Incident, pending.incident_id)
    assert incident.status == "AWAITING_APPROVAL"
    assert pending.status == "pending"
    events = [n.event_type for n in db.scalars(select(Notification)).all()]
    assert "approval.requested" in events


def test_approver_approves_and_incident_executes(pending, db, client):
    resp = client.post(
        f"/v1/approvals/{pending.id}/decision",
        json={"decision": "approved", "reason": "safe to restart"},
        headers=bearer("approver"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["decided_by"] == "approver@test.local"
    assert body["decision_reason"] == "safe to restart"
    assert body["decided_at"] is not None

    assert db.get(Incident, pending.incident_id).status == "EXECUTING"


def test_viewer_and_operator_cannot_decide(pending, client):
    for role in ("viewer", "operator"):
        resp = client.post(
            f"/v1/approvals/{pending.id}/decision",
            json={"decision": "approved", "reason": "x"},
            headers=bearer(role),
        )
        assert resp.status_code == 403, role


def test_self_approval_blocked_and_logged(sim, db, client):
    client.post(
        "/v1/policies",
        json={
            "name": "selfy-restart",
            "environment": "development",
            "action": "service.restart",
            "allowed_targets": ["selfy"],
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
                    "active_state": "failed",
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
    decision = decide(
        db,
        Proposal(
            action="service.restart",
            target="selfy",
            agent_id=uuid.UUID(sim.agent_id),
            environment="development",
            incident_id=incident.id,
        ),
    )
    approval = request_approval(db, incident, decision, requested_by="approver@test.local")
    db.commit()

    resp = client.post(
        f"/v1/approvals/{approval.id}/decision",
        json={"decision": "approved", "reason": "approving my own request"},
        headers=bearer("approver"),  # same email as requested_by
    )
    assert resp.status_code == 403
    db.refresh(approval)
    assert approval.status == "pending"
    assert db.scalar(
        select(AuditLog).where(AuditLog.event_type == "approval.self_approval_blocked")
    )

    # the database enforces it too, not just the API
    with pytest.raises(Exception, match="approver_is_not_requester"):
        db.execute(
            text("update approvals set decided_by = requested_by where id = :id"),
            {"id": str(approval.id)},
        )
    db.rollback()


def test_rejection_escalates_and_notifies(pending, db, client, hook):
    resp = client.post(
        f"/v1/approvals/{pending.id}/decision",
        json={"decision": "rejected", "reason": "not during business hours"},
        headers=bearer("approver"),
    )
    assert resp.status_code == 200
    assert db.get(Incident, pending.incident_id).status == "ESCALATED"
    events = [n.event_type for n in db.scalars(select(Notification)).all()]
    assert "incident.escalated" in events


def test_expiry_escalates(pending, db):
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert expire_pending(db) == 1
    db.refresh(pending)
    assert pending.status == "expired"
    assert db.get(Incident, pending.incident_id).status == "ESCALATED"
    assert db.scalar(select(AuditLog).where(AuditLog.event_type == "approval.expired"))


def test_decided_approval_cannot_be_redecided(pending, db, client):
    first = client.post(
        f"/v1/approvals/{pending.id}/decision",
        json={"decision": "approved", "reason": "ok"},
        headers=bearer("approver"),
    )
    assert first.status_code == 200
    second = client.post(
        f"/v1/approvals/{pending.id}/decision",
        json={"decision": "rejected", "reason": "changed my mind"},
        headers=bearer("approver", email="other-approver@test.local"),
    )
    assert second.status_code == 409


def test_pending_list_visible_to_viewer(pending, client):
    resp = client.get("/v1/approvals?status=pending", headers=bearer("viewer"))
    assert resp.status_code == 200
    assert len(resp.json()["approvals"]) == 1