import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.audit import record
from app.commands.service import expire_command, record_result
from app.db import get_db
from app.models import Agent, AgentConfig, Command, EnrollmentToken, Environment
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


class CommandResultIn(BaseModel):
    status: str = Field(pattern="^(succeeded|failed|rejected|duplicate|timeout)$")
    exit_status: int | None = None
    output: str | None = Field(default=None, max_length=8192)
    error: str | None = Field(default=None, max_length=2048)
    duration_ms: int | None = None


def owned_command(command_id: str, agent: Agent, db: Session) -> Command:
    try:
        command = db.get(Command, uuid.UUID(command_id))
    except ValueError:
        command = None
    if command is None or command.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="command not found")
    return command


def expired_guard(db: Session, command: Command) -> None:
    now = db.scalar(select(func.now()))
    if command.expires_at < now:
        expire_command(db, command)
        db.commit()
        raise HTTPException(status_code=409, detail="command expired")


@router.get("/commands")
def pending_commands(
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    now = db.scalar(select(func.now()))
    commands = db.scalars(
        select(Command)
        .where(
            Command.agent_id == agent.id,
            Command.status.in_(("pending", "delivered")),
            Command.expires_at >= now,
        )
        .order_by(Command.created_at)
    ).all()
    return {
        "commands": [
            {
                "id": str(c.id),
                "action": c.action,
                "params": c.params,
                "idempotency_key": c.idempotency_key,
                "expires_at": c.expires_at.isoformat(),
            }
            for c in commands
        ]
    }


@router.post("/commands/{command_id}/ack")
def ack_command(
    command_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    command = owned_command(command_id, agent, db)
    if command.status not in ("pending", "delivered"):
        raise HTTPException(status_code=409, detail=f"command is {command.status}")
    expired_guard(db, command)
    command.status = "delivered"
    command.acked_at = datetime.now(UTC)
    db.commit()
    return {"status": "delivered"}


@router.post("/commands/{command_id}/result")
def command_result(
    command_id: str,
    payload: CommandResultIn,
    request: Request,
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    command = owned_command(command_id, agent, db)
    if command.status not in ("pending", "delivered"):
        raise HTTPException(status_code=409, detail=f"command is {command.status}")
    expired_guard(db, command)
    record_result(
        db,
        command,
        status=payload.status,
        exit_status=payload.exit_status,
        output=payload.output,
        error=payload.error,
        duration_ms=payload.duration_ms,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    db.commit()
    return {"status": command.status}


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
