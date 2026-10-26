from conftest import operator_token
from sim_agent import SimAgent
from test_enrollment import make_token


def bearer(role):
    return {"Authorization": f"Bearer {operator_token(role)}"}


def test_me_returns_role(anon_client):
    resp = anon_client.get("/v1/me", headers=bearer("operator"))
    assert resp.status_code == 200
    assert resp.json()["role"] == "operator"
    assert anon_client.get("/v1/me").status_code == 401


def test_agent_inventory_requires_operator(anon_client, db):
    agent = SimAgent(anon_client)
    agent.enroll(make_token(db))
    agent.heartbeat(version="1.2.3")

    assert anon_client.get("/v1/agents", headers=bearer("viewer")).status_code == 403

    body = anon_client.get("/v1/agents", headers=bearer("operator")).json()
    row = next(a for a in body["agents"] if a["hostname"] == "sim-agent-01")
    assert row["environment"] == "development"
    assert row["version"] == "1.2.3"
    assert row["last_seen_at"] is not None
    assert "secret" not in row


def test_environments_list(anon_client):
    body = anon_client.get("/v1/environments", headers=bearer("viewer")).json()
    assert set(body["environments"]) == {"development", "staging", "production"}
