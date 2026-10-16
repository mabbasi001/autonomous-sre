import os

os.environ["SRE_DATABASE_URL"] = os.environ.get(
    "SRE_TEST_DATABASE_URL", "postgresql+psycopg://sre:sre@localhost:5432/sre_test"
)

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

TEST_URL = os.environ["SRE_DATABASE_URL"]
ADMIN_URL = TEST_URL.rsplit("/", 1)[0] + "/sre"
TEST_DBNAME = TEST_URL.rsplit("/", 1)[1]


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
        conn.execute(text("truncate agents, enrollment_tokens, audit_logs cascade"))


@pytest.fixture()
def client(test_database):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture()
def db(test_database):
    from app.db import SessionLocal

    session = SessionLocal()
    yield session
    session.close()
