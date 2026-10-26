import os

os.environ["SRE_DATABASE_URL"] = os.environ.get(
    "SRE_TEST_DATABASE_URL", "postgresql+psycopg://sre:sre@localhost:5432/sre_test"
)
os.environ["SRE_MIGRATION_DATABASE_URL"] = os.environ["SRE_DATABASE_URL"]

import base64
import json
import time

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine, text

from app.config import settings

TEST_URL = os.environ["SRE_DATABASE_URL"]
ADMIN_URL = TEST_URL.rsplit("/", 1)[0] + "/sre"
TEST_DBNAME = TEST_URL.rsplit("/", 1)[1]

TEST_TENANT = "test-tenant"
TEST_CLIENT_ID = "test-client"
TEST_ISSUER = f"https://login.microsoftonline.com/{TEST_TENANT}/v2.0"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64url(n: int) -> str:
    data = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


_public = _private_key.public_key().public_numbers()
TEST_JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": "test-key",
            "n": _b64url(_public.n),
            "e": _b64url(_public.e),
        }
    ]
}

settings.oidc_tenant_id = TEST_TENANT
settings.oidc_client_id = TEST_CLIENT_ID
settings.oidc_jwks = json.dumps(TEST_JWKS)
settings.slack_webhook_url = ""  # a developer's .env must not leak into tests
settings.anthropic_api_key = ""


def operator_token(
    role: str | None,
    email: str | None = None,
    issuer: str = TEST_ISSUER,
    audience: str = TEST_CLIENT_ID,
) -> str:
    email = email or f"{role}@test.local"
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": email,
        "preferred_username": email,
        "name": email,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()) - 10,
    }
    if role is not None:
        claims["roles"] = [role]
    return jwt.encode(claims, _private_key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture(scope="session", autouse=True)
def test_database():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if conn.execute(
            text("select 1 from pg_database where datname = :name"), {"name": TEST_DBNAME}
        ).scalar():
            conn.execute(text(f'drop database "{TEST_DBNAME}" with (force)'))
        conn.execute(text(f'create database "{TEST_DBNAME}"'))
    admin.dispose()
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def clean_tables(test_database):
    yield
    from app.db import engine

    with engine.begin() as conn:
        conn.execute(
            text(
                "truncate agents, enrollment_tokens, audit_logs, notifications,"
                " kill_switches cascade"
            )
        )


@pytest.fixture()
def client(test_database):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(
        app, headers={"Authorization": f"Bearer {operator_token('admin')}"}
    )


@pytest.fixture()
def anon_client(test_database):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture()
def db(test_database):
    from app.db import SessionLocal

    session = SessionLocal()
    yield session
    session.close()
