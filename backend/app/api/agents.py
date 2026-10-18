import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.audit import record
from app.db import get_db
from app.models import Agent, AgentConfig, EnrollmentToken, Environment
from app.security import authenticated_agent, token_hash

router = APIRouter(prefix="/v1/agents")


class EnrollRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    hostname: str = Field(min_length=1, max_length=253)
    environment: str = Field(min_length=1, max_length=64)


class EnrollResponse(BaseModel):
    agent_id: str
    secret: str


class HeartbeatRequest(BaseModel):
    version: str = Field(min_length=1, max_length=64)


@router.post("/enroll", response_model=EnrollResponse, status_code=201)
def enroll(payload: EnrollRequest, request: Request, db: Session = Depends(get_db)):
    token = db.scalar(
        select(EnrollmentToken).where(EnrollmentToken.token_hash == token_hash(payload.token))
    )
    if token is None or token.used_at is not None or token.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="invalid enrollment token")

    environment = db.get(Environment, token.environment_id)
    if environment is None or environment.name != payload.environment:
        raise HTTPException(status_code=403, detail="token not valid for this environment")

    # atomic claim: guards against the same token enrolling twice concurrently
    claimed = db.execute(
        update(EnrollmentToken)
        .where(EnrollmentToken.id == token.id, EnrollmentToken.used_at.is_(None))
        .values(used_at=func.now())
    )
    if claimed.rowcount != 1:
        raise HTTPException(status_code=401, detail="invalid enrollment token")

    agent = Agent(
        environment_id=token.environment_id,
        hostname=payload.hostname,
        status="active",
        secret=secrets.token_hex(32),
    )
    db.add(agent)
    db.flush()
    record(
        db,
        actor_type="agent",
        actor_id=str(agent.id),
        event_type="agent.enrolled",
        entity_type="agent",
        entity_id=str(agent.id),
        correlation_id=getattr(request.state, "correlation_id", None),
        detail={"hostname": payload.hostname, "environment": environment.name},
    )
    db.commit()
    return EnrollResponse(agent_id=str(agent.id), secret=agent.secret)


@router.get("/config")
def get_config(
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    latest = db.scalar(
        select(AgentConfig)
        .where(AgentConfig.agent_id == agent.id)
        .order_by(AgentConfig.version.desc())
        .limit(1)
    )
    if latest is None:
        return {"version": 0, "config": {}}
    return {"version": latest.version, "config": latest.config}


@router.post("/heartbeat")
def heartbeat(
    payload: HeartbeatRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    agent = db.merge(agent)
    agent.agent_version = payload.version
    agent.last_seen_at = datetime.now(UTC)
    db.commit()
    return {"status": "ok"}


@router.post("/credentials/rotate", response_model=EnrollResponse)
def rotate_credentials(
    request: Request,
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    agent = db.merge(agent)
    agent.secret = secrets.token_hex(32)
    record(
        db,
        actor_type="agent",
        actor_id=str(agent.id),
        event_type="agent.credentials_rotated",
        entity_type="agent",
        entity_id=str(agent.id),
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    db.commit()
    return EnrollResponse(agent_id=str(agent.id), secret=agent.secret)
