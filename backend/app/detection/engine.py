"""Server-side rule evaluation: turns normalized events into alerts.

Nothing becomes an incident without a rule that fired. Evaluation is
idempotent over the event queue (processed_at + SKIP LOCKED) and over
condition persistence (a state only alerts on transition).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Alert, AlertRule, Environment, Event, RuleState

OPERATORS = {
    ">": lambda value, threshold: value > threshold,
    "<": lambda value, threshold: value < threshold,
}


class _KeepPlaceholder(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_fingerprint(rule: AlertRule, agent_id: uuid.UUID, payload: dict) -> str:
    values = {k: v for k, v in payload.items() if isinstance(v, str | int | float | bool)}
    values["agent_id"] = str(agent_id)
    return rule.fingerprint_template.format_map(_KeepPlaceholder(values))


def active_rules(db: Session, rule_type: str | None = None) -> list[AlertRule]:
    rows = db.scalars(
        select(AlertRule).order_by(AlertRule.name, AlertRule.version.desc())
    ).all()
    latest: dict[str, AlertRule] = {}
    for rule in rows:
        latest.setdefault(rule.name, rule)
    return [
        r
        for r in latest.values()
        if r.enabled and (rule_type is None or r.rule_type == rule_type)
    ]


def in_scope(rule: AlertRule, environment_name: str | None) -> bool:
    wanted = rule.scope.get("environment")
    return wanted is None or wanted == environment_name


def firing_alert(db: Session, rule_name: str, fingerprint: str) -> Alert | None:
    return db.scalar(
        select(Alert).where(
            Alert.rule_name == rule_name,
            Alert.fingerprint == fingerprint,
            Alert.status == "firing",
        )
    )


def fire(db: Session, rule: AlertRule, fingerprint: str, event: Event | None, agent_id, env_id):
    if firing_alert(db, rule.name, fingerprint) is not None:
        return 0
    db.add(
        Alert(
            rule_name=rule.name,
            rule_version=rule.version,
            fingerprint=fingerprint,
            severity=rule.severity,
            status="firing",
            agent_id=agent_id,
            environment_id=env_id,
            event_ids=[str(event.id)] if event is not None else [],
            context={"event_type": event.type, "payload": event.payload} if event else {},
            fired_at=datetime.now(UTC),
        )
    )
    db.flush()  # session runs with autoflush off; later lookups in the same batch must see this
    return 1


def resolve(db: Session, rule_name: str, fingerprint: str) -> None:
    alert = firing_alert(db, rule_name, fingerprint)
    if alert is not None:
        alert.status = "resolved"
        alert.resolved_at = datetime.now(UTC)
        db.flush()


def previous_event(db: Session, event: Event, identity: dict) -> Event | None:
    query = (
        select(Event)
        .where(
            Event.agent_id == event.agent_id,
            Event.type == event.type,
            Event.occurred_at < event.occurred_at,
        )
        .order_by(Event.occurred_at.desc())
        .limit(1)
    )
    for field, value in identity.items():
        query = query.where(Event.payload[field].astext == str(value))
    return db.scalar(query)


def evaluate_state_change(db: Session, rule: AlertRule, event: Event) -> int:
    cond = rule.condition
    if event.type != cond["event_type"]:
        return 0
    payload = event.payload
    if any(payload.get(k) != v for k, v in cond.get("match", {}).items()):
        return 0

    bad_values = cond["bad_values"]
    is_bad = payload.get(cond["field"]) in bad_values
    identity = {f: payload.get(f) for f in cond.get("identity_fields", [])}
    prev = previous_event(db, event, identity)
    was_bad = prev is not None and prev.payload.get(cond["field"]) in bad_values

    fingerprint = render_fingerprint(rule, event.agent_id, payload)
    if is_bad and not was_bad:
        return fire(db, rule, fingerprint, event, event.agent_id, event.environment_id)
    if not is_bad and was_bad:
        resolve(db, rule.name, fingerprint)
    return 0


def evaluate_threshold(db: Session, rule: AlertRule, event: Event) -> int:
    cond = rule.condition
    if event.kind != "metric" or event.type != cond["metric"]:
        return 0
    value = event.payload.get("value")
    if not isinstance(value, int | float):
        return 0

    fingerprint = render_fingerprint(rule, event.agent_id, event.payload)
    state_row = db.scalar(
        select(RuleState).where(
            RuleState.rule_name == rule.name,
            RuleState.agent_id == event.agent_id,
            RuleState.key == fingerprint,
        )
    )

    if not OPERATORS[cond["operator"]](value, cond["threshold"]):
        if state_row is not None:
            db.delete(state_row)
            db.flush()
        resolve(db, rule.name, fingerprint)
        return 0

    if state_row is None:
        db.add(
            RuleState(
                rule_name=rule.name,
                agent_id=event.agent_id,
                key=fingerprint,
                state={"breach_started_at": event.occurred_at.isoformat(), "fired": False},
            )
        )
        db.flush()
        return 0

    started_at = datetime.fromisoformat(state_row.state["breach_started_at"])
    sustained = (event.occurred_at - started_at).total_seconds() >= cond["duration_seconds"]
    if state_row.state.get("fired") or not sustained:
        return 0

    state_row.state = state_row.state | {"fired": True}
    return fire(db, rule, fingerprint, event, event.agent_id, event.environment_id)


def process_pending_events(db: Session, limit: int = 200) -> int:
    rules = [r for r in active_rules(db) if r.rule_type in ("state_change", "threshold")]
    environments = {e.id: e.name for e in db.scalars(select(Environment))}
    events = db.scalars(
        select(Event)
        .where(Event.processed_at.is_(None))
        .order_by(Event.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()

    fired = 0
    for event in events:
        for rule in rules:
            if not in_scope(rule, environments.get(event.environment_id)):
                continue
            if rule.rule_type == "state_change":
                fired += evaluate_state_change(db, rule, event)
            else:
                fired += evaluate_threshold(db, rule, event)
        event.processed_at = datetime.now(UTC)
    db.commit()
    return fired


def absence_sweep(db: Session) -> int:
    now = datetime.now(UTC)
    environments = {e.id: e.name for e in db.scalars(select(Environment))}
    fired = 0
    for rule in active_rules(db, rule_type="absence"):
        cutoff = now - timedelta(seconds=rule.condition["max_silence_seconds"])
        agents = db.scalars(select(Agent).where(Agent.status == "active")).all()
        for agent in agents:
            if not in_scope(rule, environments.get(agent.environment_id)):
                continue
            if agent.last_seen_at is None:
                continue
            fingerprint = render_fingerprint(rule, agent.id, {})
            if agent.last_seen_at < cutoff:
                fired += fire(db, rule, fingerprint, None, agent.id, agent.environment_id)
            else:
                resolve(db, rule.name, fingerprint)
    db.commit()
    return fired
