from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require
from app.db import get_db
from app.models import Agent, Environment, User

router = APIRouter(prefix="/v1")


@router.get("/agents")
def list_agents(db: Session = Depends(get_db), user: User = Depends(require("operator"))):
    agents = db.scalars(select(Agent).order_by(Agent.hostname)).all()
    envs = {e.id: e.name for e in db.scalars(select(Environment))}
    return {
        "agents": [
            {
                "id": str(a.id),
                "hostname": a.hostname,
                "environment": envs.get(a.environment_id),
                "status": a.status,
                "version": a.agent_version,
                "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
            }
            for a in agents
        ]
    }


@router.get("/environments")
def list_environments(db: Session = Depends(get_db), user: User = Depends(require("viewer"))):
    envs = db.scalars(select(Environment).order_by(Environment.name)).all()
    return {"environments": [e.name for e in envs]}
