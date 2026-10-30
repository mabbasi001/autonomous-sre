"""Local-account login (interim operator auth, pre-Entra).

Only active when ``auth_secret`` is set and OIDC is not. Issues a
backend-signed session token that ``current_user`` accepts as a bearer.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.auth import issue_session
from app.config import settings
from app.db import get_db
from app.models import User
from app.passwords import verify_password

logger = logging.getLogger("auth")

router = APIRouter(prefix="/v1/auth")


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    if settings.oidc_tenant_id or not settings.auth_secret:
        # Local login is off whenever OIDC is the configured mode.
        raise HTTPException(status_code=404, detail="local login not enabled")

    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    # Verify even when the user is missing so the response time and shape
    # don't reveal which emails exist; the generic 401 is identical either way.
    ok = verify_password(body.password, user.password_hash if user else None)
    if not user or not ok:
        logger.warning("failed local login for %s", email)
        raise HTTPException(status_code=401, detail="invalid credentials")

    token, expires_in = issue_session(user)
    record(
        db,
        actor_type="user",
        actor_id=user.email,
        event_type="user.login",
        entity_type="user",
        entity_id=user.email,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    db.commit()

    return {
        "token": token,
        "expires_in": expires_in,
        "user": {"email": user.email, "display_name": user.display_name, "role": user.role},
    }
