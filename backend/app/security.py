import hashlib
import hmac
import time
import uuid

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Agent

SIGNATURE_WINDOW_SECONDS = 300


def sign(secret: str, method: str, path: str, timestamp: str, body: bytes) -> str:
    payload = "\n".join([method, path, timestamp, hashlib.sha256(body).hexdigest()])
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def authenticated_agent(
    request: Request,
    x_agent_id: str = Header(),
    x_timestamp: str = Header(),
    x_signature: str = Header(),
    db: Session = Depends(get_db),
) -> Agent:
    unauthorized = HTTPException(status_code=401, detail="invalid agent credentials")

    try:
        agent_id = uuid.UUID(x_agent_id)
        timestamp = int(x_timestamp)
    except ValueError:
        raise unauthorized from None

    if abs(time.time() - timestamp) > SIGNATURE_WINDOW_SECONDS:
        raise unauthorized

    agent = db.get(Agent, agent_id)
    if agent is None or agent.status != "active":
        raise unauthorized

    body = await request.body()
    expected = sign(agent.secret, request.method, request.url.path, x_timestamp, body)
    if not hmac.compare_digest(expected, x_signature):
        raise unauthorized

    return agent
