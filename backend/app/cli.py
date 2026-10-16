import argparse
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.audit import record
from app.db import SessionLocal
from app.models import Agent, EnrollmentToken, Environment
from app.security import token_hash


def create_enrollment_token(environment: str, ttl_minutes: int) -> None:
    with SessionLocal() as db:
        env = db.scalar(select(Environment).where(Environment.name == environment))
        if env is None:
            sys.exit(f"unknown environment: {environment}")
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        db.add(
            EnrollmentToken(
                token_hash=token_hash(token), environment_id=env.id, expires_at=expires_at
            )
        )
        record(
            db,
            actor_type="user",
            event_type="enrollment_token.created",
            entity_type="environment",
            entity_id=str(env.id),
            detail={"environment": environment, "ttl_minutes": ttl_minutes},
        )
        db.commit()
    print(f"token (shown once): {token}")
    print(f"environment: {environment}")
    print(f"expires: {expires_at.isoformat()}")


def revoke_agent(agent_id: str) -> None:
    with SessionLocal() as db:
        agent = db.get(Agent, uuid.UUID(agent_id))
        if agent is None:
            sys.exit(f"unknown agent: {agent_id}")
        agent.status = "revoked"
        record(
            db,
            actor_type="user",
            event_type="agent.revoked",
            entity_type="agent",
            entity_id=agent_id,
        )
        db.commit()
    print(f"revoked agent {agent_id}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="sre-admin")
    sub = parser.add_subparsers(dest="command", required=True)

    p_token = sub.add_parser("create-enrollment-token")
    p_token.add_argument("--environment", required=True)
    p_token.add_argument("--ttl-minutes", type=int, default=15)

    p_revoke = sub.add_parser("revoke-agent")
    p_revoke.add_argument("agent_id")

    args = parser.parse_args()
    if args.command == "create-enrollment-token":
        create_enrollment_token(args.environment, args.ttl_minutes)
    elif args.command == "revoke-agent":
        revoke_agent(args.agent_id)


if __name__ == "__main__":
    main()
