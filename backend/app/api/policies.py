from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.auth import require
from app.db import get_db
from app.models import Environment, KillSwitch, Policy, User
from app.policies.catalogue import CATALOGUE

router = APIRouter(prefix="/v1")


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    environment: str | None = None
    action: str
    allowed_targets: list[str] = Field(min_length=1, max_length=100)
    mode: str
    rate_limit: dict = Field(default={"max": 3, "window_seconds": 3600})
    cooldown_seconds: int = Field(default=300, ge=0)
    max_retries: int = Field(default=2, ge=0)
    enabled: bool = True


def serialize_policy(policy: Policy) -> dict:
    return {
        "name": policy.name,
        "version": policy.version,
        "environment": policy.environment,
        "action": policy.action,
        "allowed_targets": policy.allowed_targets,
        "mode": policy.mode,
        "rate_limit": policy.rate_limit,
        "cooldown_seconds": policy.cooldown_seconds,
        "max_retries": policy.max_retries,
        "enabled": policy.enabled,
    }


@router.get("/policies")
def list_policies(db: Session = Depends(get_db), user: User = Depends(require("viewer"))):
    rows = db.scalars(select(Policy).order_by(Policy.name, Policy.version.desc())).all()
    latest: dict[str, Policy] = {}
    for policy in rows:
        latest.setdefault(policy.name, policy)
    return {"policies": [serialize_policy(p) for p in latest.values()]}


@router.post("/policies", status_code=201)
def create_policy(
    payload: PolicyIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("admin")),
):
    if payload.action not in CATALOGUE:
        raise HTTPException(status_code=422, detail=f"action not in catalogue: {payload.action}")
    if payload.mode not in ("auto", "approval"):
        raise HTTPException(status_code=422, detail=f"unknown mode: {payload.mode}")
    if set(payload.rate_limit) != {"max", "window_seconds"}:
        raise HTTPException(status_code=422, detail="rate_limit needs max and window_seconds")

    current = db.scalar(select(func.max(Policy.version)).where(Policy.name == payload.name))
    policy = Policy(version=(current or 0) + 1, **payload.model_dump())
    db.add(policy)
    record(
        db,
        actor_type="user",
        actor_id=user.email,
        event_type="policy.updated",
        entity_type="policy",
        entity_id=payload.name,
        correlation_id=getattr(request.state, "correlation_id", None),
        detail={"version": policy.version},
    )
    db.commit()
    return serialize_policy(policy)


class KillSwitchIn(BaseModel):
    engaged: bool
    reason: str = Field(min_length=1, max_length=512)


def serialize_switch(switch: KillSwitch) -> dict:
    return {
        "scope": switch.scope,
        "engaged": switch.engaged,
        "reason": switch.reason,
        "updated_at": switch.updated_at.isoformat() if switch.updated_at else None,
    }


@router.get("/kill-switches")
def list_kill_switches(db: Session = Depends(get_db), user: User = Depends(require("viewer"))):
    rows = db.scalars(select(KillSwitch).order_by(KillSwitch.scope)).all()
    return {"kill_switches": [serialize_switch(s) for s in rows]}


@router.put("/kill-switches/{scope}")
def set_kill_switch(
    scope: str,
    payload: KillSwitchIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("admin")),
):
    if scope != "global":
        prefix, _, name = scope.partition(":")
        env = db.scalar(select(Environment).where(Environment.name == name))
        if prefix != "environment" or env is None:
            raise HTTPException(status_code=422, detail=f"unknown scope: {scope}")

    switch = db.scalar(select(KillSwitch).where(KillSwitch.scope == scope))
    if switch is None:
        switch = KillSwitch(scope=scope)
        db.add(switch)
    switch.engaged = payload.engaged
    switch.reason = payload.reason
    switch.updated_at = datetime.now(UTC)
    record(
        db,
        actor_type="user",
        actor_id=user.email,
        event_type="kill_switch.engaged" if payload.engaged else "kill_switch.disengaged",
        entity_type="kill_switch",
        entity_id=scope,
        correlation_id=getattr(request.state, "correlation_id", None),
        detail={"reason": payload.reason},
    )
    db.commit()
    return serialize_switch(switch)
