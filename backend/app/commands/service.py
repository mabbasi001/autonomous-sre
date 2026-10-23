"""Command dispatch: an allowed or approved action becomes a command that
exactly one agent executes at most once. The kill switch is re-checked
here, independently of the proposal-time check.
"""

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.approvals.service import request_approval
from app.audit import record
from app.config import settings
from app.incidents.manager import transition
from app.models import ActionExecution, Command, Incident, PolicyDecision, RemediationRun
from app.policies.engine import Proposal, decide, kill_switch_engaged

TERMINAL_COMMAND_STATUSES = {"succeeded", "failed", "expired"}


def dispatch(
    db: Session,
    incident: Incident,
    decision: PolicyDecision,
    params: dict,
    correlation_id: str | None = None,
) -> Command | None:
    """Create the command, unless a kill switch engaged since the decision."""
    scope = kill_switch_engaged(db, decision.environment)
    if scope is not None:
        record(
            db,
            actor_type="system",
            event_type="command.blocked",
            entity_type="incident",
            entity_id=str(incident.id),
            correlation_id=correlation_id,
            detail={"action": decision.action, "target": decision.target, "kill_switch": scope},
        )
        if incident.status in ("EXECUTING", "REMEDIATION_PROPOSED", "AWAITING_APPROVAL"):
            transition(
                db,
                incident,
                "ESCALATED",
                actor_type="system",
                reason=f"kill switch {scope} engaged at dispatch time",
                correlation_id=correlation_id,
            )
        db.commit()
        return None

    now = db.scalar(select(func.now()))
    command = Command(
        agent_id=decision.agent_id,
        incident_id=incident.id,
        policy_decision_id=decision.id,
        action=decision.action,
        params=params,
        idempotency_key=str(uuid.uuid4()),
        status="pending",
        expires_at=now + timedelta(seconds=settings.command_expiry_seconds),
    )
    db.add(command)
    db.flush()
    db.add(
        RemediationRun(
            incident_id=incident.id,
            command_id=command.id,
            action=decision.action,
            target=decision.target,
            status="running",
        )
    )
    record(
        db,
        actor_type="system",
        event_type="command.created",
        entity_type="command",
        entity_id=str(command.id),
        correlation_id=correlation_id,
        detail={
            "action": decision.action,
            "target": decision.target,
            "incident_id": str(incident.id),
            "expires_at": command.expires_at.isoformat(),
        },
    )
    db.commit()
    return command


def execute_remediation(
    db: Session,
    incident: Incident,
    action: str,
    target: str,
    params: dict,
    correlation_id: str | None = None,
) -> PolicyDecision:
    """The proposal → policy → (approval | dispatch) orchestration."""
    decision = decide(
        db,
        Proposal(
            action=action,
            target=target,
            agent_id=incident.agent_id,
            environment=_environment_name(db, incident),
            incident_id=incident.id,
        ),
        correlation_id=correlation_id,
    )

    if decision.outcome == "allow":
        if incident.status == "REMEDIATION_PROPOSED":
            transition(
                db,
                incident,
                "EXECUTING",
                actor_type="system",
                reason=f"policy permits automatic {action} on {target}",
                correlation_id=correlation_id,
            )
        dispatch(db, incident, decision, params, correlation_id)
    elif decision.outcome == "approval_required":
        approval = request_approval(db, incident, decision, correlation_id=correlation_id)
        approval.params = params
        db.commit()
    else:
        if incident.status == "REMEDIATION_PROPOSED":
            transition(
                db,
                incident,
                "ESCALATED",
                actor_type="system",
                reason=f"policy denied {action} on {target}: {decision.reason}",
                correlation_id=correlation_id,
            )
        db.commit()
    return decision


def record_result(
    db: Session,
    command: Command,
    *,
    status: str,
    exit_status: int | None,
    output: str | None,
    error: str | None,
    duration_ms: int | None,
    correlation_id: str | None = None,
) -> None:
    db.add(
        ActionExecution(
            command_id=command.id,
            status=status,
            exit_status=exit_status,
            output=output[:4096] if output else None,
            error=error[:1024] if error else None,
            duration_ms=duration_ms,
        )
    )
    now = db.scalar(select(func.now()))
    command.status = "succeeded" if status == "succeeded" else "failed"
    command.completed_at = now

    run = db.scalar(select(RemediationRun).where(RemediationRun.command_id == command.id))
    if run is not None:
        run.status = command.status
        run.completed_at = now

    record(
        db,
        actor_type="agent",
        actor_id=str(command.agent_id),
        event_type=f"command.{command.status}",
        entity_type="command",
        entity_id=str(command.id),
        correlation_id=correlation_id,
        detail={"action": command.action, "result_status": status, "error": error},
    )

    incident = db.get(Incident, command.incident_id) if command.incident_id else None
    if incident is not None and incident.status == "EXECUTING":
        if command.status == "succeeded":
            transition(
                db,
                incident,
                "VERIFYING",
                actor_type="system",
                reason=f"{command.action} executed; verifying recovery",
                correlation_id=correlation_id,
            )
        else:
            transition(
                db,
                incident,
                "ESCALATED",
                actor_type="system",
                reason=f"{command.action} failed: {error or status}",
                correlation_id=correlation_id,
            )


def expire_command(db: Session, command: Command) -> None:
    now = db.scalar(select(func.now()))
    command.status = "expired"
    command.completed_at = now
    run = db.scalar(select(RemediationRun).where(RemediationRun.command_id == command.id))
    if run is not None:
        run.status = "expired"
        run.completed_at = now
    record(
        db,
        actor_type="system",
        event_type="command.expired",
        entity_type="command",
        entity_id=str(command.id),
        detail={"action": command.action},
    )
    incident = db.get(Incident, command.incident_id) if command.incident_id else None
    if incident is not None and incident.status == "EXECUTING":
        transition(
            db,
            incident,
            "ESCALATED",
            actor_type="system",
            reason=f"{command.action} expired before execution",
        )


def expire_commands(db: Session) -> int:
    now = db.scalar(select(func.now()))
    stale = db.scalars(
        select(Command)
        .where(Command.status.in_(("pending", "delivered")), Command.expires_at < now)
        .with_for_update(skip_locked=True)
    ).all()
    for command in stale:
        expire_command(db, command)
    db.commit()
    return len(stale)


def _environment_name(db: Session, incident: Incident) -> str:
    from app.models import Environment

    environment = db.get(Environment, incident.environment_id)
    return environment.name if environment else "unknown"
