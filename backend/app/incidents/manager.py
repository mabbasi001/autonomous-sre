"""Incident lifecycle: alerts become deduplicated incidents with evidence.

Dedup key is the alert fingerprint: a firing alert attaches to the open
incident with the same fingerprint instead of creating a new one.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.audit import record
from app.models import Agent, Alert, Environment, Event, Incident, IncidentEvent, IncidentEvidence
from app.notifications.service import notify

TERMINAL_STATUSES = {"RESOLVED", "CLOSED"}

TRANSITIONS = {
    "OPEN": {"INVESTIGATING", "CLOSED"},
    "INVESTIGATING": {"DIAGNOSED", "MANUAL_TRIAGE"},
    "DIAGNOSED": {"REMEDIATION_PROPOSED"},
    "MANUAL_TRIAGE": {"REMEDIATION_PROPOSED"},
    "REMEDIATION_PROPOSED": {"EXECUTING", "AWAITING_APPROVAL", "ESCALATED"},
    "AWAITING_APPROVAL": {"EXECUTING", "ESCALATED"},
    "EXECUTING": {"VERIFYING", "ESCALATED"},
    "VERIFYING": {"RESOLVED", "MITIGATED", "ESCALATED"},
    "MITIGATED": {"RESOLVED", "ESCALATED"},
    "ESCALATED": {"RESOLVED", "CLOSED"},
    "RESOLVED": {"CLOSED"},
    "CLOSED": set(),
}

RECENT_EVIDENCE_WINDOW = timedelta(minutes=10)
RECENT_EVIDENCE_LIMIT = 50


class InvalidTransition(Exception):
    pass


def notify_incident(db: Session, event_type: str, incident: Incident) -> None:
    agent = db.get(Agent, incident.agent_id)
    environment = db.get(Environment, incident.environment_id)
    notify(
        db,
        event_type,
        incident,
        hostname=agent.hostname if agent else "unknown",
        environment=environment.name if environment else "unknown",
    )


def open_incident_for(db: Session, fingerprint: str) -> Incident | None:
    return db.scalar(
        select(Incident).where(
            Incident.fingerprint == fingerprint,
            Incident.status.notin_(TERMINAL_STATUSES),
        )
    )


def link_events(db: Session, incident: Incident, event_ids: list[uuid.UUID]) -> None:
    if not event_ids:
        return
    rows = [
        {"id": uuid.uuid4(), "incident_id": incident.id, "event_id": event_id}
        for event_id in event_ids
    ]
    db.execute(
        pg_insert(IncidentEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["incident_id", "event_id"])
    )


def attach_alert(db: Session, incident: Incident, alert: Alert) -> None:
    alert.incident_id = incident.id
    db.add(
        IncidentEvidence(
            incident_id=incident.id,
            kind="alert",
            ref=str(alert.id),
            summary={
                "rule": alert.rule_name,
                "rule_version": alert.rule_version,
                "severity": alert.severity,
                "fingerprint": alert.fingerprint,
                "fired_at": alert.fired_at.isoformat(),
            },
        )
    )
    link_events(db, incident, [uuid.UUID(e) for e in alert.event_ids])


def open_incident(db: Session, alert: Alert) -> Incident:
    agent = db.get(Agent, alert.agent_id)
    hostname = agent.hostname if agent else str(alert.agent_id)
    incident = Incident(
        fingerprint=alert.fingerprint,
        title=f"{alert.rule_name} on {hostname}",
        status="OPEN",
        severity=alert.severity,
        agent_id=alert.agent_id,
        environment_id=alert.environment_id,
        opened_at=alert.fired_at,
    )
    db.add(incident)
    db.flush()
    attach_alert(db, incident, alert)

    # bounded context: recent events from the same agent, references only
    recent = db.scalars(
        select(Event.id)
        .where(
            Event.agent_id == alert.agent_id,
            Event.occurred_at >= alert.fired_at - RECENT_EVIDENCE_WINDOW,
        )
        .order_by(Event.occurred_at.desc())
        .limit(RECENT_EVIDENCE_LIMIT)
    ).all()
    link_events(db, incident, list(recent))

    record(
        db,
        actor_type="system",
        event_type="incident.opened",
        entity_type="incident",
        entity_id=str(incident.id),
        detail={"fingerprint": incident.fingerprint, "severity": incident.severity},
    )
    notify_incident(db, "incident.opened", incident)
    return incident


def process_new_alerts(db: Session) -> int:
    alerts = db.scalars(
        select(Alert).where(Alert.incident_id.is_(None)).order_by(Alert.fired_at)
    ).all()
    opened = 0
    for alert in alerts:
        incident = open_incident_for(db, alert.fingerprint)
        if incident is None:
            open_incident(db, alert)
            opened += 1
        else:
            attach_alert(db, incident, alert)
        db.flush()
    db.commit()
    return opened


def transition(
    db: Session,
    incident: Incident,
    to_status: str,
    *,
    actor_type: str,
    reason: str,
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> Incident:
    allowed = TRANSITIONS.get(incident.status, set())
    if to_status not in allowed:
        raise InvalidTransition(f"{incident.status} -> {to_status} is not allowed")

    from_status = incident.status
    incident.status = to_status
    if to_status in TERMINAL_STATUSES:
        incident.closed_at = datetime.now(UTC)
    record(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="incident.transition",
        entity_type="incident",
        entity_id=str(incident.id),
        correlation_id=correlation_id,
        detail={"from": from_status, "to": to_status, "reason": reason},
    )
    if to_status == "ESCALATED":
        notify_incident(db, "incident.escalated", incident)
    return incident
