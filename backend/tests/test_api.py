from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_healthz_sets_correlation_id():
    resp = client.get("/healthz")
    assert resp.headers.get("x-correlation-id")


def test_healthz_echoes_provided_correlation_id():
    resp = client.get("/healthz", headers={"x-correlation-id": "test-123"})
    assert resp.headers["x-correlation-id"] == "test-123"


def test_metrics():
    client.get("/healthz")  # ensure at least one counted request
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "sre_http_requests_total" in resp.text
