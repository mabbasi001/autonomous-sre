from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require
from app.db import get_db
from app.models import AuditLog, User

router = APIRouter(prefix="/v1/audit-logs")


@router.get("")
def list_audit_logs(
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: str | None = None,
    correlation_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require("viewer")),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if correlation_id:
        query = query.where(AuditLog.correlation_id == correlation_id)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at <= until)

    return {
        "audit_logs": [
            {
                "id": str(row.id),
                "actor_type": row.actor_type,
                "actor_id": row.actor_id,
                "event_type": row.event_type,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "correlation_id": row.correlation_id,
                "detail": row.detail,
                "created_at": row.created_at.isoformat(),
            }
            for row in db.scalars(query).all()
        ]
    }
