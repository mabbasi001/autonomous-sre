from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.db import get_db
from app.models import AlertRule

router = APIRouter(prefix="/v1/alert-rules")

RULE_TYPES = {"state_change", "threshold", "absence"}


class AlertRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    rule_type: str
    severity: str = Field(min_length=1, max_length=16)
    scope: dict = Field(default_factory=dict)
    condition: dict
    fingerprint_template: str = Field(min_length=1, max_length=256)
    enabled: bool = True


def serialize(rule: AlertRule) -> dict:
    return {
        "name": rule.name,
        "version": rule.version,
        "rule_type": rule.rule_type,
        "severity": rule.severity,
        "scope": rule.scope,
        "condition": rule.condition,
        "fingerprint_template": rule.fingerprint_template,
        "enabled": rule.enabled,
    }


@router.get("")
def list_rules(db: Session = Depends(get_db)):
    rows = db.scalars(select(AlertRule).order_by(AlertRule.name, AlertRule.version.desc())).all()
    latest: dict[str, AlertRule] = {}
    for rule in rows:
        latest.setdefault(rule.name, rule)
    return {"rules": [serialize(r) for r in latest.values()]}


@router.post("", status_code=201)
def create_rule(payload: AlertRuleIn, request: Request, db: Session = Depends(get_db)):
    if payload.rule_type not in RULE_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown rule_type: {payload.rule_type}")

    current = db.scalar(
        select(func.max(AlertRule.version)).where(AlertRule.name == payload.name)
    )
    rule = AlertRule(version=(current or 0) + 1, **payload.model_dump())
    db.add(rule)
    record(
        db,
        actor_type="user",
        event_type="alert_rule.updated",
        entity_type="alert_rule",
        entity_id=payload.name,
        correlation_id=getattr(request.state, "correlation_id", None),
        detail={"version": rule.version},
    )
    db.commit()
    return serialize(rule)
