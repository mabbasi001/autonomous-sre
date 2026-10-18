import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.incidents.manager import TRANSITIONS, InvalidTransition, transition
from app.models import Event, Incident, IncidentEvent, IncidentEvidence

router = APIRouter(prefix="/v1/incidents")


class TransitionIn(BaseModel):
    to_status: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=512)


def summarize(incident: Incident) -> dict:
    return {
        "id": str(incident.id),
        "title": incident.title,
        "status": incident.status,
        "severity": incident.severity,
        "fingerprint": incident.fingerprint,
        "agent_id": str(incident.agent_id),
        "environment_id": str(incident.environment_id),
        "opened_at": incident.opened_at.isoformat(),
        "closed_at": incident.closed_at.isoformat() if incident.closed_at else None,
    }


def get_incident(incident_id: str, db: Session) -> Incident:
    try:
        incident = db.get(Incident, uuid.UUID(incident_id))
    except ValueError:
        incident = None
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


@router.get("")
def list_incidents(status: str | None = None, db: Session = Depends(get_db)):
    query = select(Incident).order_by(Incident.opened_at.desc())
    if status:
        query = query.where(Incident.status == status)
    return {"incidents": [summarize(i) for i in db.scalars(query).all()]}


@router.get("/{incident_id}")
def incident_detail(incident_id: str, db: Session = Depends(get_db)):
    incident = get_incident(incident_id, db)

    evidence = db.scalars(
        select(IncidentEvidence)
        .where(IncidentEvidence.incident_id == incident.id)
        .order_by(IncidentEvidence.created_at)
    ).all()
    events = db.execute(
        select(Event.id, Event.kind, Event.type, Event.occurred_at)
        .join(IncidentEvent, IncidentEvent.event_id == Event.id)
        .where(IncidentEvent.incident_id == incident.id)
        .order_by(Event.occurred_at)
    ).all()

    return summarize(incident) | {
        "evidence": [
            {"kind": e.kind, "ref": e.ref, "summary": e.summary} for e in evidence
        ],
        "events": [
            {
                "id": str(e.id),
                "kind": e.kind,
                "type": e.type,
                "occurred_at": e.occurred_at.isoformat(),
            }
            for e in events
        ],
        "allowed_transitions": sorted(TRANSITIONS.get(incident.status, set())),
    }


@router.post("/{incident_id}/transition")
def transition_incident(
    incident_id: str,
    payload: TransitionIn,
    request: Request,
    db: Session = Depends(get_db),
):
    incident = get_incident(incident_id, db)
    try:
        transition(
            db,
            incident,
            payload.to_status,
            actor_type="user",
            reason=payload.reason,
            correlation_id=getattr(request.state, "correlation_id", None),
        )
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return summarize(incident)
