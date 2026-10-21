"""Operator authentication (Entra ID OIDC bearer tokens) and RBAC.

Roles come from the app registration's `roles` claim. When OIDC is not
configured, development falls back to a synthetic admin so the API stays
usable before the tenant exists; any other environment refuses.
"""

import json
import logging

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

logger = logging.getLogger("auth")

ROLE_ORDER = ["viewer", "operator", "approver", "admin"]

_jwks_cache: dict | None = None


def _jwks() -> dict:
    global _jwks_cache
    if settings.oidc_jwks:
        return json.loads(settings.oidc_jwks)
    if _jwks_cache is None:
        url = (
            f"https://login.microsoftonline.com/{settings.oidc_tenant_id}"
            "/discovery/v2.0/keys"
        )
        _jwks_cache = httpx.get(url, timeout=10).json()
    return _jwks_cache


def validate_token(token: str) -> dict:
    header = jwt.get_unverified_header(token)
    key = next((k for k in _jwks()["keys"] if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise jwt.InvalidTokenError("unknown signing key")
    return jwt.decode(
        token,
        key=jwt.PyJWK(key).key,
        algorithms=["RS256"],
        audience=settings.oidc_client_id,
        issuer=f"https://login.microsoftonline.com/{settings.oidc_tenant_id}/v2.0",
    )


def highest_role(roles: list[str]) -> str | None:
    held = [r for r in ROLE_ORDER if r in roles]
    return held[-1] if held else None


async def current_user(
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    if not settings.oidc_tenant_id:
        if settings.environment == "development":
            return _dev_admin(db)
        raise HTTPException(status_code=401, detail="operator auth not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = validate_token(authorization.removeprefix("Bearer "))
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token") from None

    role = highest_role(claims.get("roles", []))
    if role is None:
        raise HTTPException(status_code=403, detail="no role assigned")

    email = claims.get("preferred_username") or claims.get("email") or claims["sub"]
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=claims.get("name", email), role=role)
        db.add(user)
    else:
        user.role = role
        user.display_name = claims.get("name", user.display_name)
    db.flush()
    return user


def _dev_admin(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == "dev@localhost"))
    if user is None:
        user = User(email="dev@localhost", display_name="Dev Admin", role="admin")
        db.add(user)
        db.flush()
        logger.warning("OIDC not configured: using synthetic dev admin")
    return user


def require(minimum: str):
    async def dependency(user: User = Depends(current_user)) -> User:
        if ROLE_ORDER.index(user.role) < ROLE_ORDER.index(minimum):
            raise HTTPException(status_code=403, detail=f"requires {minimum} role")
        return user

    return dependency
