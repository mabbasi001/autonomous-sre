"""Approval lifecycle: an approval_required policy decision waits here for
a human. Approval moves the incident to EXECUTING; rejection or expiry
escalates it.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.config import settings
from app.incidents.manager import notify_incident, transition
from app.models import Approval, Incident, PolicyDecision


class ApprovalError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def request_approval(
    db: Session,
    incident: Incident,
    decision: PolicyDecision,
    requested_by: str = "system",
    correlation_id: str | None = None,
) -> Approval:
    now = db.scalar(select(func.now()))
    approval = Approval(
        incident_id=incident.id,
        policy_decision_id=decision.id,
        action=decision.action,
        target=decision.target,
        status="pending",
        requested_by=requested_by,
        expires_at=now + timedelta(seconds=settings.approval_ttl_seconds),
    )
    db.add(approval)
    db.flush()
    if incident.status == "REMEDIATION_PROPOSED":
        transition(
            db,
            incident,
            "AWAITING_APPROVAL",
            actor_type="system",
            reason=f"approval required for {decision.action} on {decision.target}",
            correlation_id=correlation_id,
        )
    record(
        db,
        actor_type="system",
        event_type="approval.requested",
        entity_type="approval",
        entity_id=str(approval.id),
        correlation_id=correlation_id,
        detail={"action": decision.action, "target": decision.target},
    )
    notify_incident(db, "approval.requested", incident)
    return approval


def decide_approval(
    db: Session,
    approval: Approval,
    decision: str,
    decided_by: str,
    reason: str,
    correlation_id: str | None = None,
) -> Approval:
    if approval.status != "pending":
        raise ApprovalError(409, f"approval already {approval.status}")
    if decided_by == approval.requested_by:
        record(
            db,
            actor_type="user",
            actor_id=decided_by,
            event_type="approval.self_approval_blocked",
            entity_type="approval",
            entity_id=str(approval.id),
            correlation_id=correlation_id,
        )
        db.commit()
        raise ApprovalError(403, "requester cannot decide their own approval")

    now = db.scalar(select(func.now()))
    if approval.expires_at < now:
        expire(db, approval)
        db.commit()
        raise ApprovalError(409, "approval has expired")

    approval.status = "approved" if decision == "approved" else "rejected"
    approval.decided_by = decided_by
    approval.decision_reason = reason
    approval.decided_at = now

    incident = db.get(Incident, approval.incident_id)
    if incident.status == "AWAITING_APPROVAL":
        transition(
            db,
            incident,
            "EXECUTING" if approval.status == "approved" else "ESCALATED",
            actor_type="user",
            actor_id=decided_by,
            reason=reason,
            correlation_id=correlation_id,
        )
    record(
        db,
        actor_type="user",
        actor_id=decided_by,
        event_type=f"approval.{approval.status}",
        entity_type="approval",
        entity_id=str(approval.id),
        correlation_id=correlation_id,
        detail={"reason": reason, "action": approval.action, "target": approval.target},
    )
    return approval


def expire(db: Session, approval: Approval) -> None:
    approval.status = "expired"
    incident = db.get(Incident, approval.incident_id)
    if incident is not None and incident.status == "AWAITING_APPROVAL":
        transition(
            db,
            incident,
            "ESCALATED",
            actor_type="system",
            reason="approval expired without a decision",
        )
    record(
        db,
        actor_type="system",
        event_type="approval.expired",
        entity_type="approval",
        entity_id=str(approval.id),
    )


def expire_pending(db: Session) -> int:
    now = db.scalar(select(func.now()))
    stale = db.scalars(
        select(Approval)
        .where(Approval.status == "pending", Approval.expires_at < now)
        .with_for_update(skip_locked=True)
    ).all()
    for approval in stale:
        expire(db, approval)
    db.commit()
    return len(stale)
