"""Recovery verification: a separate code path from remediation.

The agent only runs read-only checks; this worker makes the decision.
Read-only verification commands are created directly (not through the
remediation dispatcher), so kill switches stop remediation but never
stop verification. Absence of evidence never resolves an incident.
"""

import logging
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.config import settings
from app.incidents.manager import notify_incident, transition
from app.models import (
    ActionExecution,
    AgentConfig,
    Command,
    Incident,
    IncidentEvidence,
    RemediationRun,
    Verification,
)

logger = logging.getLogger("verification")

CENTRAL_PROBE_TIMEOUT = 3


def probe_url(url: str) -> str:
    """Central HTTP probe. Returns pass/fail/unreachable."""
    try:
        response = httpx.get(url, timeout=CENTRAL_PROBE_TIMEOUT)
    except httpx.ConnectError:
        return "unreachable"
    except httpx.HTTPError:
        return "fail"
    return "pass" if response.status_code < 400 else "fail"


def build_checks(db: Session, incident: Incident) -> list[dict]:
    checks = []
    run = db.scalars(
        select(RemediationRun)
        .where(RemediationRun.incident_id == incident.id, RemediationRun.status == "succeeded")
        .order_by(RemediationRun.created_at.desc())
    ).first()
    if run is not None and run.action in ("service.restart", "service.status"):
        checks.append({"kind": "service.status", "params": {"unit": run.target}})

    config = db.scalars(
        select(AgentConfig)
        .where(AgentConfig.agent_id == incident.agent_id)
        .order_by(AgentConfig.version.desc())
    ).first()
    if config is not None:
        for http_check in config.config.get("http_checks", [])[:2]:
            checks.append(
                {
                    "kind": "http.check",
                    "params": {"url": http_check["url"], "name": http_check.get("name", "check")},
                }
            )
    return checks


def dispatch_check_command(db: Session, incident: Incident, check: dict) -> Command:
    now = db.scalar(select(func.now()))
    command = Command(
        agent_id=incident.agent_id,
        incident_id=incident.id,
        action=check["kind"],
        params=check["params"],
        idempotency_key=str(uuid.uuid4()),
        status="pending",
        expires_at=now + timedelta(seconds=settings.command_expiry_seconds),
    )
    db.add(command)
    db.flush()
    return command


def start_round(db: Session, incident: Incident, attempt: int) -> Verification | None:
    checks = build_checks(db, incident)
    if not checks:
        transition(
            db,
            incident,
            "ESCALATED",
            actor_type="system",
            reason="no verification plan could be built",
        )
        return None
    now = db.scalar(select(func.now()))
    verification = Verification(
        incident_id=incident.id,
        attempt=attempt,
        status="pending",
        checks=checks,
        not_before=now + timedelta(seconds=settings.verify_settle_seconds),
    )
    db.add(verification)
    db.flush()
    return verification


def dispatch_due(db: Session, verification: Verification, incident: Incident) -> None:
    checks = []
    for check in verification.checks:
        command = dispatch_check_command(db, incident, check)
        checks.append(check | {"command_id": str(command.id), "outcome": "pending"})
    verification.checks = checks
    verification.status = "running"


def check_outcome(db: Session, check: dict) -> tuple[str, str]:
    """Returns (outcome, detail) for a dispatched check."""
    command = db.get(Command, uuid.UUID(check["command_id"]))
    if command.status == "expired":
        return "expired", "agent did not execute the check in time"
    if command.status in ("pending", "delivered"):
        return "pending", ""

    execution = db.scalars(
        select(ActionExecution)
        .where(ActionExecution.command_id == command.id)
        .order_by(ActionExecution.created_at.desc())
    ).first()
    output = (execution.output or "") if execution else ""

    if command.status != "succeeded":
        return "fail", (execution.error if execution and execution.error else command.status)

    if check["kind"] == "service.status":
        if "ActiveState=active" in output:
            return "pass", output.strip()
        return "fail", output.strip() or "service not active"

    # http.check through the agent: exit_status carries the HTTP code
    agent_outcome = "pass"
    detail = output.strip()
    if execution is None or execution.status != "succeeded":
        agent_outcome = "fail"

    central = probe_url(check["params"]["url"])
    if central == "unreachable":
        return agent_outcome, f"{detail} (central probe unreachable, agent result used)"
    if central == agent_outcome == "pass":
        return "pass", f"{detail} (central probe agrees)"
    return "fail", f"{detail} (agent={agent_outcome}, central={central})"


def conclude(db: Session, verification: Verification, incident: Incident) -> None:
    outcomes = []
    checks = []
    for check in verification.checks:
        if check["outcome"] == "pending":
            outcome, detail = check_outcome(db, check)
            check = check | {"outcome": outcome, "detail": detail}
        outcomes.append(check["outcome"])
        checks.append(check)
    verification.checks = checks

    if "pending" in outcomes:
        return  # evidence not in yet; never decide early

    now = db.scalar(select(func.now()))
    if "expired" in outcomes:
        verification.status = "unreachable"
        verification.decided_at = now
        decide(db, incident, verification, "ESCALATED", "verification could not complete")
        return

    passed = outcomes.count("pass")
    if passed == len(outcomes):
        verification.status = "passed"
        verification.decided_at = now
        decide(db, incident, verification, "RESOLVED", "all verification checks passed")
        return

    if verification.attempt < settings.verify_max_attempts:
        verification.status = "failed"
        verification.decided_at = now
        start_round(db, incident, verification.attempt + 1)
        return

    verification.decided_at = now
    if passed > 0:
        verification.status = "partial"
        decide(db, incident, verification, "MITIGATED", "partial recovery: some checks failing")
    else:
        verification.status = "failed"
        decide(db, incident, verification, "ESCALATED", "verification checks failed")


def decide(
    db: Session, incident: Incident, verification: Verification, to_status: str, reason: str
):
    db.add(
        IncidentEvidence(
            incident_id=incident.id,
            kind="verification",
            ref=str(verification.id),
            summary={
                "attempt": verification.attempt,
                "status": verification.status,
                "checks": [
                    {"kind": c["kind"], "outcome": c["outcome"], "detail": c.get("detail", "")}
                    for c in verification.checks
                ],
            },
        )
    )
    record(
        db,
        actor_type="system",
        event_type=f"verification.{verification.status}",
        entity_type="incident",
        entity_id=str(incident.id),
        detail={"attempt": verification.attempt, "decision": to_status},
    )
    if incident.status == "VERIFYING":
        transition(db, incident, to_status, actor_type="system", reason=reason)
    if to_status == "RESOLVED":
        notify_incident(db, "incident.resolved", incident)


def run_verifications(db: Session) -> int:
    decided = 0
    now = db.scalar(select(func.now()))

    verifying = db.scalars(
        select(Incident).where(Incident.status == "VERIFYING").with_for_update(skip_locked=True)
    ).all()
    for incident in verifying:
        active = db.scalar(
            select(func.count())
            .select_from(Verification)
            .where(
                Verification.incident_id == incident.id, Verification.decided_at.is_(None)
            )
        )
        if active == 0 and not db.scalar(
            select(Verification.id).where(Verification.incident_id == incident.id)
        ):
            start_round(db, incident, attempt=1)

    pending = db.scalars(
        select(Verification).where(
            Verification.status == "pending", Verification.not_before <= now
        )
    ).all()
    for verification in pending:
        incident = db.get(Incident, verification.incident_id)
        if incident.status == "VERIFYING":
            dispatch_due(db, verification, incident)

    running = db.scalars(
        select(Verification).where(Verification.status == "running")
    ).all()
    for verification in running:
        incident = db.get(Incident, verification.incident_id)
        conclude(db, verification, incident)
        if verification.decided_at is not None:
            decided += 1
    db.commit()
    return decided
