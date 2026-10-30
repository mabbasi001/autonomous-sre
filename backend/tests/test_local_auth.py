"""Interim local-account auth (email + password → backend session token).

These run in local-auth mode (OIDC off, auth_secret set), the inverse of
the rest of the suite, so each test opts in via the local_auth fixture.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import User
from app.passwords import hash_password, verify_password

SECRET = "local-auth-test-secret-at-least-32-bytes"
PASSWORD = "CorrectHorse9!"


@pytest.fixture()
def local_auth(test_database, db, monkeypatch):
    """Switch to local-auth mode and seed an admin local account."""
    monkeypatch.setattr(settings, "oidc_tenant_id", "")
    monkeypatch.setattr(settings, "auth_secret", SECRET)
    user = User(
        email="admin@local",
        display_name="Local Admin",
        role="admin",
        password_hash=hash_password(PASSWORD),
    )
    db.add(user)
    db.commit()
    yield
    db.query(User).delete()
    db.commit()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_roundtrip():
    h = hash_password("s3cret")
    assert h.startswith("scrypt$")
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)


def test_login_success_authorizes_requests(local_auth):
    client = TestClient(app)
    resp = client.post("/v1/auth/login", json={"email": "admin@local", "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["role"] == "admin"
    token = body["token"]

    me = client.get("/v1/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["email"] == "admin@local"

    # The session token is accepted on a real platform endpoint too.
    assert client.get("/v1/incidents", headers=bearer(token)).status_code == 200


def test_login_writes_audit_row(local_auth, db):
    from sqlalchemy import select

    from app.models import AuditLog

    client = TestClient(app)
    resp = client.post("/v1/auth/login", json={"email": "admin@local", "password": PASSWORD})
    assert resp.status_code == 200
    row = db.scalar(select(AuditLog).where(AuditLog.event_type == "user.login"))
    assert row is not None
    assert row.actor_id == "admin@local"
    assert row.correlation_id is not None


def test_login_rejects_bad_password_and_unknown_user(local_auth):
    client = TestClient(app)
    assert (
        client.post("/v1/auth/login", json={"email": "admin@local", "password": "nope"}).status_code
        == 401
    )
    assert (
        client.post("/v1/auth/login", json={"email": "ghost@local", "password": "x"}).status_code
        == 401
    )


def test_email_is_case_insensitive(local_auth):
    client = TestClient(app)
    resp = client.post("/v1/auth/login", json={"email": "ADMIN@Local", "password": PASSWORD})
    assert resp.status_code == 200


def test_bad_or_missing_session_token_rejected(local_auth):
    client = TestClient(app)
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers=bearer("garbage")).status_code == 401


def test_role_is_read_from_db_not_token(local_auth, db):
    """A session token carries only identity; role changes take effect at once."""
    client = TestClient(app)
    token = client.post(
        "/v1/auth/login", json={"email": "admin@local", "password": PASSWORD}
    ).json()["token"]
    assert client.get("/v1/me", headers=bearer(token)).json()["role"] == "admin"

    user = db.query(User).filter(User.email == "admin@local").one()
    user.role = "viewer"
    db.commit()
    # Same token, downgraded role — a privileged route is now forbidden.
    assert client.get("/v1/me", headers=bearer(token)).json()["role"] == "viewer"
    policy = {
        "name": "x",
        "action": "service.restart",
        "allowed_targets": ["x"],
        "mode": "approval",
    }
    assert client.post("/v1/policies", json=policy, headers=bearer(token)).status_code == 403


def test_session_void_after_account_removed(local_auth, db):
    client = TestClient(app)
    token = client.post(
        "/v1/auth/login", json={"email": "admin@local", "password": PASSWORD}
    ).json()["token"]
    db.query(User).filter(User.email == "admin@local").delete()
    db.commit()
    assert client.get("/v1/me", headers=bearer(token)).status_code == 401


def test_login_disabled_when_oidc_configured(test_database, monkeypatch):
    monkeypatch.setattr(settings, "oidc_tenant_id", "some-tenant")
    monkeypatch.setattr(settings, "auth_secret", SECRET)
    client = TestClient(app)
    resp = client.post("/v1/auth/login", json={"email": "admin@local", "password": PASSWORD})
    assert resp.status_code == 404


def test_session_token_only_valid_for_session_type(local_auth):
    """A token signed with the right key but wrong type is rejected."""
    import jwt

    forged = jwt.encode({"sub": "admin@local", "typ": "other"}, SECRET, algorithm="HS256")
    client = TestClient(app)
    assert client.get("/v1/me", headers=bearer(forged)).status_code == 401
