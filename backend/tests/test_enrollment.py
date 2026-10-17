import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Agent, AuditLog, EnrollmentToken, Environment
from app.security import sign, token_hash


def make_token(db, environment="development", ttl_minutes=15):
    env = db.scalar(select(Environment).where(Environment.name == environment))
    token = secrets.token_urlsafe(32)
    db.add(
        EnrollmentToken(
            token_hash=token_hash(token),
            environment_id=env.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )
    )
    db.commit()
    return token


def enroll(client, db, environment="development"):
    token = make_token(db, environment)
    resp = client.post(
        "/v1/agents/enroll",
        json={"token": token, "hostname": "vm-test-01", "environment": environment},
    )
    assert resp.status_code == 201
    return resp.json()


def signed_post(client, path, payload, agent_id, secret, timestamp=None):
    body = json.dumps(payload).encode()
    ts = str(timestamp if timestamp is not None else int(time.time()))
    return client.post(
        path,
        content=body,
        headers={
            "content-type": "application/json",
            "x-agent-id": agent_id,
            "x-timestamp": ts,
            "x-signature": sign(secret, "POST", path, ts, body),
        },
    )


def test_enroll_returns_credentials_and_audits(client, db):
    creds = enroll(client, db)
    agent = db.get(Agent, uuid.UUID(creds["agent_id"]))
    assert agent.status == "active"
    assert agent.secret == creds["secret"]
    audit = db.scalar(select(AuditLog).where(AuditLog.event_type == "agent.enrolled"))
    assert audit.entity_id == creds["agent_id"]
    assert audit.correlation_id


def test_token_is_single_use(client, db):
    token = make_token(db)
    body = {"token": token, "hostname": "vm", "environment": "development"}
    assert client.post("/v1/agents/enroll", json=body).status_code == 201
    assert client.post("/v1/agents/enroll", json=body).status_code == 401


def test_expired_token_rejected(client, db):
    token = make_token(db, ttl_minutes=-1)
    resp = client.post(
        "/v1/agents/enroll",
        json={"token": token, "hostname": "vm", "environment": "development"},
    )
    assert resp.status_code == 401


def test_wrong_environment_rejected(client, db):
    token = make_token(db, environment="development")
    resp = client.post(
        "/v1/agents/enroll",
        json={"token": token, "hostname": "vm", "environment": "production"},
    )
    assert resp.status_code == 403


def test_unknown_token_rejected(client, db):
    resp = client.post(
        "/v1/agents/enroll",
        json={"token": "x" * 43, "hostname": "vm", "environment": "development"},
    )
    assert resp.status_code == 401


def test_heartbeat_updates_agent(client, db):
    creds = enroll(client, db)
    resp = signed_post(
        client, "/v1/agents/heartbeat", {"version": "0.1.0"}, creds["agent_id"], creds["secret"]
    )
    assert resp.status_code == 200
    agent = db.get(Agent, uuid.UUID(creds["agent_id"]))
    db.refresh(agent)
    assert agent.agent_version == "0.1.0"
    assert agent.last_seen_at is not None


def test_tampered_body_rejected(client, db):
    creds = enroll(client, db)
    body = json.dumps({"version": "0.1.0"}).encode()
    ts = str(int(time.time()))
    sig = sign(creds["secret"], "POST", "/v1/agents/heartbeat", ts, body)
    resp = client.post(
        "/v1/agents/heartbeat",
        content=json.dumps({"version": "9.9.9"}).encode(),
        headers={
            "content-type": "application/json",
            "x-agent-id": creds["agent_id"],
            "x-timestamp": ts,
            "x-signature": sig,
        },
    )
    assert resp.status_code == 401


def test_stale_timestamp_rejected(client, db):
    creds = enroll(client, db)
    resp = signed_post(
        client,
        "/v1/agents/heartbeat",
        {"version": "0.1.0"},
        creds["agent_id"],
        creds["secret"],
        timestamp=int(time.time()) - 600,
    )
    assert resp.status_code == 401


def test_unknown_agent_id_rejected(client, db):
    resp = signed_post(
        client, "/v1/agents/heartbeat", {"version": "0.1.0"}, str(uuid.uuid4()), "not-a-secret"
    )
    assert resp.status_code == 401


def test_revoked_agent_rejected(client, db):
    creds = enroll(client, db)
    agent = db.get(Agent, uuid.UUID(creds["agent_id"]))
    agent.status = "revoked"
    db.commit()
    resp = signed_post(
        client, "/v1/agents/heartbeat", {"version": "0.1.0"}, creds["agent_id"], creds["secret"]
    )
    assert resp.status_code == 401


def test_rotation_invalidates_old_secret(client, db):
    creds = enroll(client, db)
    resp = signed_post(
        client, "/v1/agents/credentials/rotate", {}, creds["agent_id"], creds["secret"]
    )
    assert resp.status_code == 200
    new_secret = resp.json()["secret"]
    assert new_secret != creds["secret"]

    old = signed_post(
        client, "/v1/agents/heartbeat", {"version": "0.1.0"}, creds["agent_id"], creds["secret"]
    )
    assert old.status_code == 401
    new = signed_post(
        client, "/v1/agents/heartbeat", {"version": "0.1.0"}, creds["agent_id"], new_secret
    )
    assert new.status_code == 200
