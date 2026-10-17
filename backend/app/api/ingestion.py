import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Agent, Event
from app.security import authenticated_agent

router = APIRouter(prefix="/v1")

MAX_BATCH = 500


class MetricIn(BaseModel):
    event_id: uuid.UUID
    name: str = Field(min_length=1, max_length=128)
    value: float
    labels: dict[str, str] = Field(default_factory=dict)
    occurred_at: datetime


class LogExcerptIn(BaseModel):
    event_id: uuid.UUID
    unit: str = Field(min_length=1, max_length=128)
    lines: list[str] = Field(max_length=200)
    occurred_at: datetime


class EventIn(BaseModel):
    event_id: uuid.UUID
    type: str = Field(min_length=1, max_length=128)
    payload: dict
    occurred_at: datetime


class MetricsBatch(BaseModel):
    metrics: list[MetricIn] = Field(min_length=1, max_length=MAX_BATCH)


class LogsBatch(BaseModel):
    logs: list[LogExcerptIn] = Field(min_length=1, max_length=MAX_BATCH)


class EventsBatch(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=MAX_BATCH)


def store(db: Session, agent: Agent, rows: list[dict]) -> dict:
    stmt = (
        pg_insert(Event)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["client_event_id"])
        .returning(Event.id)
    )
    accepted = len(db.execute(stmt).all())
    db.commit()
    return {"accepted": accepted, "duplicates": len(rows) - accepted}


def base_row(agent: Agent, event_id: uuid.UUID, occurred_at: datetime) -> dict:
    return {
        "id": uuid.uuid4(),
        "client_event_id": event_id,
        "agent_id": agent.id,
        "environment_id": agent.environment_id,
        "occurred_at": occurred_at,
    }


@router.post("/telemetry/metrics")
def ingest_metrics(
    batch: MetricsBatch,
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    rows = [
        base_row(agent, m.event_id, m.occurred_at)
        | {"kind": "metric", "type": m.name, "payload": {"value": m.value, "labels": m.labels}}
        for m in batch.metrics
    ]
    return store(db, agent, rows)


@router.post("/telemetry/logs")
def ingest_logs(
    batch: LogsBatch,
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    rows = [
        base_row(agent, entry.event_id, entry.occurred_at)
        | {
            "kind": "log",
            "type": "log.excerpt",
            "payload": {"unit": entry.unit, "lines": entry.lines},
        }
        for entry in batch.logs
    ]
    return store(db, agent, rows)


@router.post("/events")
def ingest_events(
    batch: EventsBatch,
    db: Session = Depends(get_db),
    agent: Agent = Depends(authenticated_agent),
):
    rows = [
        base_row(agent, e.event_id, e.occurred_at)
        | {"kind": "event", "type": e.type, "payload": e.payload}
        for e in batch.events
    ]
    return store(db, agent, rows)
