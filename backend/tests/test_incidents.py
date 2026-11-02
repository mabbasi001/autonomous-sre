from datetime import UTC, datetime, timedelta

import pytest
from sim_agent import SimAgent
from sqlalchemy import select
from test_enrollment import make_token

from app.detection.engine import process_pending_events
from app.incidents.manager import process_new_alerts
from app.models import Alert, AuditLog, Incident, IncidentEvent


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


def pipeline(db):
    process_pending_events(db)
    process_new_alerts(db)


def service_state(state: str) -> dict:
    return {
        "type": "systemd.service",
        "payload": {"unit": "nginx", "active_state": state, "sub_state": "x", "restarts": 0},
    }


def incidents(db):
    return db.scalars(select(Incident).order_by(Incident.opened_at)).all()


def test_service_down_opens_single_incident(sim, db):
    sim.send("/v1/events", [service_state("inactive")])
    pipeline(db)

    found = incidents(db)
    assert len(found) == 1
    assert found[0].status == "OPEN"
    assert found[0].fingerprint == f"systemd:nginx:{sim.agent_id}"
    assert "systemd-service-down" in found[0].title

    sim.send("/v1/events", [service_state("inactive")])
    pipeline(db)
    assert len(incidents(db)) == 1


def test_flapping_one_incident_many_events(sim, db):
    sim.replay("flapping")
    pipeline(db)

    found = incidents(db)
    assert len(found) == 1

    attached = db.scalars(
        select(IncidentEvent).where(IncidentEvent.incident_id == found[0].id)
    ).all()
    assert len(attached) >= 5

    alerts = db.scalars(select(Alert)).all()
    assert len(alerts) == 3  # three down transitions
    assert all(a.incident_id == found[0].id for a in alerts)


def test_different_failure_same_vm_is_separate_incident(sim, db):
    sim.send("/v1/events", [service_state("inactive")])
    now = datetime.now(UTC)
    sim.send(
        "/v1/telemetry/metrics",
        [
            {
                "name": "host.disk_used_percent",
                "value": 95.0,
                "occurred_at": (now - timedelta(minutes=6)).isoformat(),
            },
            {"name": "host.disk_used_percent", "value": 96.0, "occurred_at": now.isoformat()},
        ],
    )
    pipeline(db)

    found = incidents(db)
    assert len(found) == 2
    assert {i.fingerprint for i in found} == {
        f"systemd:nginx:{sim.agent_id}",
        f"disk:{sim.agent_id}",
    }


def test_invalid_transition_rejected(sim, db, client):
    sim.send("/v1/events", [service_state("inactive")])
    pipeline(db)
    incident = incidents(db)[0]

    resp = client.post(
        f"/v1/incidents/{incident.id}/transition",
        json={"to_status": "EXECUTING", "reason": "skipping ahead"},
    )
    assert resp.status_code == 409
    db.refresh(incident)
    assert incident.status == "OPEN"


def test_transition_records_actor_and_reason(sim, db, client):
    sim.send("/v1/events", [service_state("inactive")])
    pipeline(db)
    incident = incidents(db)[0]

    resp = client.post(
        f"/v1/incidents/{incident.id}/transition",
        json={"to_status": "INVESTIGATING", "reason": "taking a look"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "INVESTIGATING"

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.event_type == "incident.transition",
            AuditLog.entity_id == str(incident.id),
        )
    )
    assert audit.actor_type == "user"
    assert audit.detail == {"from": "OPEN", "to": "INVESTIGATING", "reason": "taking a look"}


def test_close_as_false_positive(sim, db, client):
    sim.send("/v1/events", [service_state("inactive")])
    pipeline(db)
    incident = incidents(db)[0]

    resp = client.post(
        f"/v1/incidents/{incident.id}/transition",
        json={"to_status": "CLOSED", "reason": "false positive"},
    )
    assert resp.status_code == 200
    db.refresh(incident)
    assert incident.status == "CLOSED"
    assert incident.closed_at is not None


def test_new_incident_after_close(sim, db, client):
    sim.send("/v1/events", [service_state("inactive")])
    pipeline(db)
    first = incidents(db)[0]
    client.post(
        f"/v1/incidents/{first.id}/transition",
        json={"to_status": "CLOSED", "reason": "duplicate"},
    )

    sim.send("/v1/events", [service_state("active")])
    sim.send("/v1/events", [service_state("inactive")])
    pipeline(db)

    found = incidents(db)
    assert len(found) == 2
    assert found[1].status == "OPEN"


def test_detail_returns_references_not_bulk_logs(sim, db, client):
    sim.replay("nginx_down")
    pipeline(db)
    incident = next(
        i for i in incidents(db) if i.fingerprint == f"systemd:nginx:{sim.agent_id}"
    )

    resp = client.get(f"/v1/incidents/{incident.id}")
    assert resp.status_code == 200
    body = resp.json()

    kinds = {e["kind"] for e in body["evidence"]}
    assert "alert" in kinds
    event_types = {e["type"] for e in body["events"]}
    assert "log.excerpt" in event_types  # referenced, but by id only
    assert "bind() to 0.0.0.0:80 failed" not in resp.text
    assert all(set(e) == {"id", "kind", "type", "occurred_at"} for e in body["events"])
    assert "OPEN" == body["status"] and "INVESTIGATING" in body["allowed_transitions"]