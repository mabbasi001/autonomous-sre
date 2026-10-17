import argparse
import json
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.audit import record
from app.db import SessionLocal
from app.models import Agent, AgentConfig, EnrollmentToken, Environment
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


def set_agent_config(agent_id: str, config_path: str) -> None:
    with open(config_path) as f:
        config = json.load(f)
    with SessionLocal() as db:
        agent = db.get(Agent, uuid.UUID(agent_id))
        if agent is None:
            sys.exit(f"unknown agent: {agent_id}")
        current = db.scalar(
            select(func.max(AgentConfig.version)).where(AgentConfig.agent_id == agent.id)
        )
        version = (current or 0) + 1
        db.add(AgentConfig(agent_id=agent.id, version=version, config=config))
        record(
            db,
            actor_type="user",
            event_type="agent_config.updated",
            entity_type="agent",
            entity_id=agent_id,
            detail={"version": version},
        )
        db.commit()
    print(f"agent {agent_id} config version {version}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="sre-admin")
    sub = parser.add_subparsers(dest="command", required=True)

    p_token = sub.add_parser("create-enrollment-token")
    p_token.add_argument("--environment", required=True)
    p_token.add_argument("--ttl-minutes", type=int, default=15)

    p_revoke = sub.add_parser("revoke-agent")
    p_revoke.add_argument("agent_id")

    p_config = sub.add_parser("set-agent-config")
    p_config.add_argument("agent_id")
    p_config.add_argument("--file", required=True)

    args = parser.parse_args()
    if args.command == "create-enrollment-token":
        create_enrollment_token(args.environment, args.ttl_minutes)
    elif args.command == "revoke-agent":
        revoke_agent(args.agent_id)
    elif args.command == "set-agent-config":
        set_agent_config(args.agent_id, args.file)


if __name__ == "__main__":
    main()
