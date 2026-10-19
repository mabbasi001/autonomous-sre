"""Slack/Teams webhook notifications. Enqueueing is transactional with the
triggering change; delivery happens in the worker and can never block or
fail the pipeline.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Incident, Notification

logger = logging.getLogger("notifications")

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30

HEADLINES = {
    "incident.opened": "incident opened",
    "incident.escalated": "incident ESCALATED",
    "approval.requested": "approval required",
}


def build_message(event_type: str, incident: Incident, hostname: str, environment: str) -> dict:
    headline = HEADLINES.get(event_type, event_type)
    return {
        "text": (
            f"[{incident.severity.upper()}] {headline}: {incident.title}\n"
            f"environment: {environment} | host: {hostname} | status: {incident.status}\n"
            f"incident: {incident.id}"
        )
    }


def notify(
    db: Session, event_type: str, incident: Incident, hostname: str, environment: str
) -> None:
    if not settings.slack_webhook_url:
        return
    db.add(
        Notification(
            event_type=event_type,
            target="slack",
            entity_type="incident",
            entity_id=str(incident.id),
            payload=build_message(event_type, incident, hostname, environment),
            status="pending",
            attempts=0,
            next_attempt_at=datetime.now(UTC),
        )
    )


def post_webhook(url: str, payload: dict) -> str | None:
    """Returns an error description, or None on success."""
    try:
        response = httpx.post(url, json=payload, timeout=5)
    except httpx.HTTPError as exc:
        return str(exc)
    if response.status_code >= 300:
        return f"webhook returned {response.status_code}"
    return None


def deliver_pending(db: Session) -> int:
    now = datetime.now(UTC)
    pending = db.scalars(
        select(Notification)
        .where(Notification.status == "pending", Notification.next_attempt_at <= now)
        .order_by(Notification.created_at)
        .with_for_update(skip_locked=True)
    ).all()

    sent = 0
    for notification in pending:
        error = post_webhook(settings.slack_webhook_url, notification.payload)
        notification.attempts += 1
        if error is None:
            notification.status = "sent"
            notification.sent_at = datetime.now(UTC)
            sent += 1
        else:
            notification.last_error = error
            if notification.attempts >= MAX_ATTEMPTS:
                notification.status = "failed"
                logger.error(f"notification {notification.id} failed permanently: {error}")
            else:
                delay = BACKOFF_BASE_SECONDS * 2 ** (notification.attempts - 1)
                notification.next_attempt_at = now + timedelta(seconds=delay)
    db.commit()
    return sent
