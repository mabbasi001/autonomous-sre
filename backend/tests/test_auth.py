from conftest import TEST_CLIENT_ID, operator_token

from app.config import settings

PLATFORM_READS = [
    "/v1/incidents",
    "/v1/alert-rules",
    "/v1/policies",
    "/v1/kill-switches",
    "/v1/approvals",
]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_rejected_everywhere(anon_client):
    for path in PLATFORM_READS:
        assert anon_client.get(path).status_code == 401, path
    assert anon_client.post("/v1/policies", json={}).status_code == 401
    assert (
        anon_client.put(
            "/v1/kill-switches/global", json={"engaged": True, "reason": "x"}
        ).status_code
        == 401
    )


def test_wrong_tenant_or_audience_rejected(anon_client):
    wrong_issuer = operator_token(
        "admin", issuer="https://login.microsoftonline.com/other-tenant/v2.0"
    )
    assert anon_client.get("/v1/incidents", headers=bearer(wrong_issuer)).status_code == 401

    wrong_audience = operator_token("admin", audience="some-other-app")
    assert anon_client.get("/v1/incidents", headers=bearer(wrong_audience)).status_code == 401

    assert anon_client.get("/v1/incidents", headers=bearer("garbage")).status_code == 401


def test_token_without_role_rejected(anon_client):
    token = operator_token(None, email="norole@test.local")
    assert anon_client.get("/v1/incidents", headers=bearer(token)).status_code == 403


def test_role_hierarchy(anon_client):
    viewer = bearer(operator_token("viewer"))
    operator = bearer(operator_token("operator"))
    admin = bearer(operator_token("admin"))

    assert anon_client.get("/v1/incidents", headers=viewer).status_code == 200
    assert anon_client.get("/v1/policies", headers=viewer).status_code == 200

    body = {"to_status": "CLOSED", "reason": "x"}
    fake_id = "00000000-0000-4000-8000-000000000000"
    # viewer blocked before the handler runs; operator reaches it (404)
    assert (
        anon_client.post(f"/v1/incidents/{fake_id}/transition", json=body, headers=viewer)
        .status_code
        == 403
    )
    assert (
        anon_client.post(f"/v1/incidents/{fake_id}/transition", json=body, headers=operator)
        .status_code
        == 404
    )

    policy_body = {
        "name": "authz-check",
        "action": "service.restart",
        "allowed_targets": ["x"],
        "mode": "approval",
    }
    assert anon_client.post("/v1/policies", json=policy_body, headers=operator).status_code == 403
    assert anon_client.post("/v1/policies", json=policy_body, headers=admin).status_code == 201

    switch_body = {"engaged": False, "reason": "authz check"}
    assert (
        anon_client.put("/v1/kill-switches/global", json=switch_body, headers=viewer).status_code
        == 403
    )
    assert (
        anon_client.put("/v1/kill-switches/global", json=switch_body, headers=admin).status_code
        == 200
    )


def test_dev_fallback_only_without_oidc_config(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "oidc_tenant_id", "")

    monkeypatch.setattr(settings, "environment", "development")
    assert anon_client.get("/v1/incidents").status_code == 200

    monkeypatch.setattr(settings, "environment", "production")
    assert anon_client.get("/v1/incidents").status_code == 401


def test_agent_endpoints_do_not_require_bearer(anon_client, db):
    from test_enrollment import make_token

    token = make_token(db)
    resp = anon_client.post(
        "/v1/agents/enroll",
        json={"token": token, "hostname": "vm", "environment": "development"},
    )
    assert resp.status_code == 201


def test_client_id_matches_config():
    assert settings.oidc_client_id == TEST_CLIENT_ID