import json
import uuid

import pytest
from sim_agent import SimAgent
from sqlalchemy import select
from test_enrollment import make_token

from app.models import Event


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


def stored_events(db, agent):
    return (
        db.execute(
            select(Event)
            .where(Event.agent_id == uuid.UUID(agent.agent_id))
            .order_by(Event.created_at)
        )
        .scalars()
        .all()
    )


def test_each_endpoint_normalizes_into_events(sim, db):
    assert sim.send(
        "/v1/telemetry/metrics", [{"name": "host.mem_used_percent", "value": 41.5}]
    ).status_code == 200
    assert sim.send(
        "/v1/telemetry/logs", [{"unit": "nginx", "lines": ["line one", "line two"]}]
    ).status_code == 200
    assert sim.send(
        "/v1/events",
        [{"type": "systemd.service", "payload": {"unit": "nginx", "active_state": "active"}}],
    ).status_code == 200

    events = stored_events(db, sim)
    by_kind = {e.kind: e for e in events}
    assert set(by_kind) == {"metric", "log", "event"}
    assert by_kind["metric"].type == "host.mem_used_percent"
    assert by_kind["metric"].payload["value"] == 41.5
    assert by_kind["log"].payload["lines"] == ["line one", "line two"]
    assert by_kind["event"].type == "systemd.service"
    assert all(e.environment_id is not None for e in events)


def test_unsigned_request_rejected(client):
    resp = client.post("/v1/events", json={"events": []})
    assert resp.status_code == 401


def test_oversized_payload_rejected(sim):
    resp = sim.send(
        "/v1/telemetry/logs", [{"unit": "nginx", "lines": ["x" * 7000] * 150}]
    )
    assert resp.status_code == 413


def test_oversized_batch_rejected(sim):
    items = [{"name": "m", "value": 1.0} for _ in range(501)]
    resp = sim.send("/v1/telemetry/metrics", items)
    assert resp.status_code == 422


def test_replayed_event_id_stored_once(sim, db):
    event_id = str(uuid.uuid4())
    item = {
        "event_id": event_id,
        "name": "host.load1",
        "value": 0.4,
        "occurred_at": "2026-11-01T00:00:00Z",
    }
    first = sim.signed_post("/v1/telemetry/metrics", {"metrics": [item]})
    second = sim.signed_post("/v1/telemetry/metrics", {"metrics": [item]})
    assert first.json() == {"accepted": 1, "duplicates": 0}
    assert second.json() == {"accepted": 0, "duplicates": 1}
    assert len(stored_events(db, sim)) == 1


def test_scenario_replay(sim, db):
    responses = sim.replay("nginx_down")
    assert all(r.status_code == 200 for r in responses)
    events = stored_events(db, sim)
    assert [e.type for e in events] == ["systemd.service", "http.check", "log.excerpt"]
    assert events[0].payload["active_state"] == "inactive"


def test_config_endpoint_versions(sim, db, tmp_path):
    assert sim.signed_get("/v1/agents/config").json() == {"version": 0, "config": {}}

    config = {"services": ["nginx"], "collect_interval_seconds": 30}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    from app.cli import set_agent_config

    set_agent_config(sim.agent_id, str(path))

    resp = sim.signed_get("/v1/agents/config").json()
    assert resp["version"] == 1
    assert resp["config"] == config
