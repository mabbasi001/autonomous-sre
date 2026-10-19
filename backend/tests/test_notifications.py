from datetime import UTC, datetime, timedelta

import pytest
from sim_agent import SimAgent
from sqlalchemy import select
from test_enrollment import make_token

from app.config import settings
from app.detection.engine import process_pending_events
from app.incidents.manager import process_new_alerts, transition
from app.models import Incident, Notification
from app.notifications import service


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


@pytest.fixture()
def hook(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "slack_webhook_url", "http://hook.test/webhook")
    monkeypatch.setattr(service, "post_webhook", lambda url, payload: calls.append(payload) or None)
    return calls


def pipeline(db):
    process_pending_events(db)
    process_new_alerts(db)


def nginx_down() -> dict:
    return {
        "type": "systemd.service",
        "payload": {"unit": "nginx", "active_state": "inactive", "sub_state": "x", "restarts": 0},
    }


def notifications(db):
    return db.scalars(select(Notification).order_by(Notification.created_at)).all()


def test_incident_opened_notifies(sim, db, hook):
    sim.send("/v1/events", [nginx_down()])
    pipeline(db)
    assert service.deliver_pending(db) == 1

    rows = notifications(db)
    assert len(rows) == 1
    assert rows[0].status == "sent"
    assert rows[0].attempts == 1
    text = hook[0]["text"]
    incident = db.scalar(select(Incident))
    assert "[HIGH]" in text
    assert "development" in text
    assert "sim-agent-01" in text
    assert str(incident.id) in text


def test_webhook_failure_retries_then_fails(sim, db, monkeypatch):
    monkeypatch.setattr(settings, "slack_webhook_url", "http://hook.test/webhook")
    monkeypatch.setattr(service, "post_webhook", lambda url, payload: "connection refused")

    sim.send("/v1/events", [nginx_down()])
    pipeline(db)

    service.deliver_pending(db)
    row = notifications(db)[0]
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.last_error == "connection refused"
    assert row.next_attempt_at > datetime.now(UTC)

    # not due yet: no extra attempt
    service.deliver_pending(db)
    db.refresh(row)
    assert row.attempts == 1

    for _ in range(4):
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        service.deliver_pending(db)
        db.refresh(row)
    assert row.attempts == 5
    assert row.status == "failed"

    # the pipeline itself was never affected
    assert db.scalar(select(Incident)).status == "OPEN"


def test_no_notification_without_webhook_config(sim, db):
    sim.send("/v1/events", [nginx_down()])
    pipeline(db)
    assert notifications(db) == []


def test_duplicate_alert_does_not_renotify(sim, db, hook):
    sim.send("/v1/events", [nginx_down()])
    pipeline(db)
    sim.send("/v1/events", [nginx_down()])
    pipeline(db)
    assert len(notifications(db)) == 1


def test_escalation_notifies(sim, db, hook):
    sim.send("/v1/events", [nginx_down()])
    pipeline(db)
    incident = db.scalar(select(Incident))

    for to_status in (
        "INVESTIGATING",
        "MANUAL_TRIAGE",
        "REMEDIATION_PROPOSED",
        "AWAITING_APPROVAL",
        "ESCALATED",
    ):
        transition(db, incident, to_status, actor_type="system", reason="test walk")
    db.commit()

    rows = notifications(db)
    assert [r.event_type for r in rows] == ["incident.opened", "incident.escalated"]
    service.deliver_pending(db)
    assert any("ESCALATED" in payload["text"] for payload in hook)


def test_messages_carry_no_log_content(sim, db, hook):
    sim.replay("nginx_down")
    pipeline(db)
    service.deliver_pending(db)
    for payload in hook:
        assert "bind() to 0.0.0.0:80" not in payload["text"]
        assert "rm -rf" not in payload["text"]