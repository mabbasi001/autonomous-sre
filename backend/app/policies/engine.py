"""The authoritative allow / approval_required / deny decision.

`evaluate` is a pure function over a proposal and a pre-gathered context,
so the decision logic is unit-testable without a database. `decide`
gathers the context, evaluates, and records the decision with its exact
inputs and the policy version that produced it.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.incidents.manager import TERMINAL_STATUSES
from app.models import Incident, KillSwitch, Policy, PolicyDecision
from app.policies.catalogue import READ_ONLY, risk_of

ALLOW = "allow"
APPROVAL_REQUIRED = "approval_required"
DENY = "deny"


@dataclass(frozen=True)
class Proposal:
    action: str
    target: str
    agent_id: uuid.UUID
    environment: str
    incident_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Context:
    risk: str | None
    kill_switch: str | None  # engaged scope, or None
    policy: Policy | None  # matched latest enabled policy, or None
    incident_status: str | None
    recent_count: int  # non-deny decisions inside the rate window
    last_decision_at: datetime | None
    incident_attempts: int
    now: datetime


def evaluate(proposal: Proposal, ctx: Context) -> tuple[str, str]:
    if ctx.risk is None:
        return DENY, f"action not in catalogue: {proposal.action}"
    if ctx.risk == READ_ONLY:
        return ALLOW, "read-only action"
    if ctx.kill_switch is not None:
        return DENY, f"kill switch engaged: {ctx.kill_switch}"
    if ctx.policy is None:
        return DENY, "no enabled policy allows this action for this target and environment"
    if ctx.incident_status is not None and ctx.incident_status in TERMINAL_STATUSES:
        return DENY, f"incident is {ctx.incident_status}"
    if ctx.incident_attempts >= ctx.policy.max_retries:
        return DENY, f"retry limit reached ({ctx.policy.max_retries}) for this incident"
    if ctx.recent_count >= ctx.policy.rate_limit["max"]:
        return DENY, f"rate limit reached ({ctx.policy.rate_limit['max']} per window)"
    if (
        ctx.last_decision_at is not None
        and (ctx.now - ctx.last_decision_at).total_seconds() < ctx.policy.cooldown_seconds
    ):
        return DENY, f"cooldown active ({ctx.policy.cooldown_seconds}s)"
    if ctx.policy.mode == "auto":
        return ALLOW, f"policy {ctx.policy.name} v{ctx.policy.version} permits automatic execution"
    return APPROVAL_REQUIRED, f"policy {ctx.policy.name} v{ctx.policy.version} requires approval"


def kill_switch_engaged(db: Session, environment: str) -> str | None:
    """Also the dispatch-time guard: the command dispatcher must call this
    again right before delivery."""
    for scope in ("global", f"environment:{environment}"):
        row = db.scalar(select(KillSwitch).where(KillSwitch.scope == scope))
        if row is not None and row.engaged:
            return scope
    return None


def matching_policy(db: Session, proposal: Proposal) -> Policy | None:
    rows = db.scalars(
        select(Policy)
        .where(Policy.action == proposal.action)
        .order_by(Policy.name, Policy.version.desc())
    ).all()
    latest: dict[str, Policy] = {}
    for policy in rows:
        latest.setdefault(policy.name, policy)

    candidates = [
        p
        for p in latest.values()
        if p.enabled
        and p.environment in (None, proposal.environment)
        and proposal.target in p.allowed_targets
    ]
    if not candidates:
        return None
    # environment-specific beats catch-all
    candidates.sort(key=lambda p: p.environment is None)
    return candidates[0]


def gather_context(db: Session, proposal: Proposal) -> Context:
    # decision timestamps come from the database, so the window and
    # cooldown math must use the database clock too
    now = db.scalar(select(func.now()))
    policy = matching_policy(db, proposal)

    recent_count = 0
    last_decision_at = None
    incident_attempts = 0
    if policy is not None:
        window_start = now - timedelta(seconds=policy.rate_limit["window_seconds"])
        base = [
            PolicyDecision.action == proposal.action,
            PolicyDecision.target == proposal.target,
            PolicyDecision.agent_id == proposal.agent_id,
            PolicyDecision.outcome != DENY,
        ]
        recent_count = db.scalar(
            select(func.count())
            .select_from(PolicyDecision)
            .where(*base, PolicyDecision.created_at >= window_start)
        )
        last_decision_at = db.scalar(
            select(func.max(PolicyDecision.created_at)).where(*base)
        )
        if proposal.incident_id is not None:
            incident_attempts = db.scalar(
                select(func.count())
                .select_from(PolicyDecision)
                .where(*base, PolicyDecision.incident_id == proposal.incident_id)
            )

    incident_status = None
    if proposal.incident_id is not None:
        incident = db.get(Incident, proposal.incident_id)
        incident_status = incident.status if incident else None

    return Context(
        risk=risk_of(proposal.action),
        kill_switch=kill_switch_engaged(db, proposal.environment),
        policy=policy,
        incident_status=incident_status,
        recent_count=recent_count,
        last_decision_at=last_decision_at,
        incident_attempts=incident_attempts,
        now=now,
    )


def decide(db: Session, proposal: Proposal, correlation_id: str | None = None) -> PolicyDecision:
    ctx = gather_context(db, proposal)
    outcome, reason = evaluate(proposal, ctx)

    decision = PolicyDecision(
        action=proposal.action,
        target=proposal.target,
        agent_id=proposal.agent_id,
        environment=proposal.environment,
        incident_id=proposal.incident_id,
        outcome=outcome,
        reason=reason,
        policy_name=ctx.policy.name if ctx.policy else None,
        policy_version=ctx.policy.version if ctx.policy else None,
        inputs={
            "risk": ctx.risk,
            "kill_switch": ctx.kill_switch,
            "incident_status": ctx.incident_status,
            "recent_count": ctx.recent_count,
            "last_decision_at": ctx.last_decision_at.isoformat()
            if ctx.last_decision_at
            else None,
            "incident_attempts": ctx.incident_attempts,
            "evaluated_at": ctx.now.isoformat(),
        },
    )
    db.add(decision)
    record(
        db,
        actor_type="system",
        event_type="policy.decision",
        entity_type="incident" if proposal.incident_id else "agent",
        entity_id=str(proposal.incident_id or proposal.agent_id),
        correlation_id=correlation_id,
        detail={
            "action": proposal.action,
            "target": proposal.target,
            "outcome": outcome,
            "reason": reason,
        },
    )
    db.commit()
    return decision
