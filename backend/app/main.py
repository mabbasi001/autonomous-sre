import logging
import uuid

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from app.api import (
    agents,
    alert_rules,
    approvals,
    audit,
    auth,
    incidents,
    ingestion,
    inventory,
    policies,
)
from app.auth import current_user
from app.config import settings
from app.logging import setup_logging

MAX_BODY_BYTES = 1_000_000

setup_logging(settings.log_level)
logger = logging.getLogger("api")

app = FastAPI(title="Autonomous SRE Platform", version="0.1.0", docs_url="/docs")

REQUESTS = Counter("sre_http_requests_total", "HTTP requests", ["path", "method", "status"])


@app.middleware("http")
async def correlation_and_metrics(request: Request, call_next) -> Response:
    correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        response: Response = JSONResponse(status_code=413, content={"detail": "payload too large"})
    else:
        response = await call_next(request)
    response.headers["x-correlation-id"] = correlation_id
    REQUESTS.labels(request.url.path, request.method, response.status_code).inc()
    logger.info(
        f"{request.method} {request.url.path} {response.status_code}",
        extra={"correlation_id": correlation_id},
    )
    return response


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "environment": settings.environment}


@app.get("/v1/me")
def me(user=Depends(current_user)) -> dict:
    return {"email": user.email, "display_name": user.display_name, "role": user.role}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(ingestion.router)
app.include_router(alert_rules.router)
app.include_router(incidents.router)
app.include_router(policies.router)
app.include_router(approvals.router)
app.include_router(audit.router)
app.include_router(inventory.router)
