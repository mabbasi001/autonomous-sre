import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sim_agent import SimAgent
from sqlalchemy import select
from test_enrollment import make_token

from app.detection.engine import absence_sweep, process_pending_events
from app.models import Agent, Alert, Event


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


def service_state(state: str, unit: str = "nginx") -> dict:
    return {
        "type": "systemd.service",
        "payload": {"unit": unit, "active_state": state, "sub_state": "dead", "restarts": 0},
    }


def alerts(db, rule_name=None):
    query = select(Alert).order_by(Alert.fired_at)
    if rule_name:
        query = query.where(Alert.rule_name == rule_name)
    return db.scalars(query).all()


def test_service_inactive_fires_exactly_one_alert(sim, db):
    sim.send("/v1/events", [service_state("inactive")])
    process_pending_events(db)

    fired = alerts(db, "systemd-service-down")
    assert len(fired) == 1
    assert fired[0].status == "firing"
    assert fired[0].fingerprint == f"systemd:nginx:{sim.agent_id}"

    # condition persists: repeated inactive reports are not new transitions
    sim.send("/v1/events", [service_state("inactive")])
    process_pending_events(db)
    assert len(alerts(db, "systemd-service-down")) == 1


def test_recovery_resolves_alert(sim, db):
    sim.send("/v1/events", [service_state("inactive")])
    process_pending_events(db)
    sim.send("/v1/events", [service_state("active")])
    process_pending_events(db)

    fired = alerts(db, "systemd-service-down")
    assert len(fired) == 1
    assert fired[0].status == "resolved"
    assert fired[0].resolved_at is not None


def test_any_service_fires_not_just_nginx(sim, db):
    # The rule is generic: a non-nginx unit going down must fire too.
    sim.send("/v1/events", [service_state("failed", unit="postgresql")])
    process_pending_events(db)

    fired = alerts(db, "systemd-service-down")
    assert len(fired) == 1
    assert fired[0].fingerprint == f"systemd:postgresql:{sim.agent_id}"


def test_distinct_units_are_independent_alerts(sim, db):
    sim.send(
        "/v1/events",
        [service_state("inactive", unit="redis"), service_state("failed", unit="cron")],
    )
    process_pending_events(db)

    fired = alerts(db, "systemd-service-down")
    fingerprints = {a.fingerprint for a in fired}
    assert fingerprints == {
        f"systemd:redis:{sim.agent_id}",
        f"systemd:cron:{sim.agent_id}",
    }


def test_nginx_down_scenario_fires_service_and_http_rules(sim, db):
    sim.replay("nginx_down")
    process_pending_events(db)

    assert len(alerts(db, "systemd-service-down")) == 1
    assert len(alerts(db, "http-check-failing")) == 1
    assert all(a.status == "firing" for a in alerts(db))


def disk_metric(value: float, minutes_ago: int) -> dict:
    return {
        "name": "host.disk_used_percent",
        "value": value,
        "occurred_at": (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat(),
    }


def test_threshold_spike_does_not_fire(sim, db):
    sim.send("/v1/telemetry/metrics", [disk_metric(97.0, 0)])
    process_pending_events(db)
    assert alerts(db, "disk-usage-high") == []


def test_threshold_sustained_breach_fires(sim, db):
    sim.send("/v1/telemetry/metrics", [disk_metric(95.0, 6)])
    sim.send("/v1/telemetry/metrics", [disk_metric(96.0, 0)])
    fired = process_pending_events(db)
    assert fired == 1
    assert len(alerts(db, "disk-usage-high")) == 1

    # stays breached: no second alert while firing
    sim.send("/v1/telemetry/metrics", [disk_metric(97.0, 0)])
    process_pending_events(db)
    assert len(alerts(db, "disk-usage-high")) == 1


def test_threshold_dip_resets_window(sim, db):
    sim.send("/v1/telemetry/metrics", [disk_metric(95.0, 10)])
    sim.send("/v1/telemetry/metrics", [disk_metric(50.0, 5)])
    sim.send("/v1/telemetry/metrics", [disk_metric(95.0, 0)])
    process_pending_events(db)
    assert alerts(db, "disk-usage-high") == []


def test_absence_fires_and_clears(sim, db):
    agent = db.get(Agent, uuid.UUID(sim.agent_id))
    agent.last_seen_at = datetime.now(UTC) - timedelta(seconds=200)
    db.commit()

    assert absence_sweep(db) == 1
    fired = alerts(db, "heartbeat-missing")
    assert len(fired) == 1 and fired[0].status == "firing"

    # second sweep while still silent must not duplicate
    assert absence_sweep(db) == 0

    agent = db.get(Agent, uuid.UUID(sim.agent_id))
    agent.last_seen_at = datetime.now(UTC)
    db.commit()
    absence_sweep(db)
    fired = alerts(db, "heartbeat-missing")
    assert len(fired) == 1 and fired[0].status == "resolved"


def test_replayed_event_does_not_duplicate_alert(sim, db):
    item = service_state("inactive") | {
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    sim.signed_post("/v1/events", {"events": [item]})
    sim.signed_post("/v1/events", {"events": [item]})
    process_pending_events(db)
    process_pending_events(db)  # reprocessing the queue is also a no-op

    assert len(alerts(db, "systemd-service-down")) == 1


def test_alert_records_version_and_evidence(sim, db):
    sim.send("/v1/events", [service_state("failed")])
    process_pending_events(db)

    alert = alerts(db, "systemd-service-down")[0]
    assert alert.rule_version == 1
    event = db.scalar(select(Event).where(Event.type == "systemd.service"))
    assert alert.event_ids == [str(event.id)]
    assert alert.context["payload"]["unit"] == "nginx"


def test_rule_edit_versions_and_old_alerts_keep_theirs(sim, db, client):
    sim.send("/v1/events", [service_state("inactive")])
    process_pending_events(db)
    old_alert = alerts(db, "systemd-service-down")[0]
    assert old_alert.rule_version == 1

    resp = client.post(
        "/v1/alert-rules",
        json={
            "name": "systemd-service-down",
            "rule_type": "state_change",
            "severity": "high",
            "condition": {
                "event_type": "systemd.service",                "identity_fields": ["unit"],
                "field": "active_state",
                "bad_values": ["inactive", "failed"],
            },
            "fingerprint_template": "systemd:{unit}:{agent_id}",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["version"] == 2

    listed = client.get("/v1/alert-rules").json()["rules"]
    by_name = {r["name"]: r for r in listed}
    assert by_name["systemd-service-down"]["version"] == 2

    db.refresh(old_alert)
    assert old_alert.rule_version == 1
