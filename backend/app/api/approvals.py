import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.service import ApprovalError, decide_approval
from app.auth import require
from app.db import get_db
from app.models import Approval, User

router = APIRouter(prefix="/v1/approvals")


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(min_length=1, max_length=512)


def serialize(approval: Approval) -> dict:
    return {
        "id": str(approval.id),
        "incident_id": str(approval.incident_id),
        "action": approval.action,
        "target": approval.target,
        "status": approval.status,
        "requested_by": approval.requested_by,
        "decided_by": approval.decided_by,
        "decision_reason": approval.decision_reason,
        "expires_at": approval.expires_at.isoformat(),
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
    }


@router.get("")
def list_approvals(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("viewer")),
):
    query = select(Approval).order_by(Approval.created_at.desc())
    if status:
        query = query.where(Approval.status == status)
    return {"approvals": [serialize(a) for a in db.scalars(query).all()]}


@router.post("/{approval_id}/decision")
def decide(
    approval_id: str,
    payload: DecisionIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("approver")),
):
    try:
        approval = db.get(Approval, uuid.UUID(approval_id))
    except ValueError:
        approval = None
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")

    try:
        decide_approval(
            db,
            approval,
            payload.decision,
            decided_by=user.email,
            reason=payload.reason,
            correlation_id=getattr(request.state, "correlation_id", None),
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    db.commit()
    return serialize(approval)
