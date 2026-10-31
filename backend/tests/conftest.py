"""Shared fixtures for database-backed smoke tests.

These tests need a disposable PostgreSQL database migrated to head:

    docker run -d --name bizassist-pg-test -e POSTGRES_USER=bizassist \
        -e POSTGRES_PASSWORD=bizassist -e POSTGRES_DB=bizassist -p 55432:5432 postgres:16-alpine
    set TEST_DATABASE_URL=postgresql+asyncpg://bizassist:bizassist@localhost:55432/bizassist
    alembic upgrade head   (with DATABASE_URL set to the same value)
    pytest

Every table is truncated between tests, so never point TEST_DATABASE_URL at real data.
"""
import asyncio
import os
import sys

import pytest
from cryptography.fernet import Fernet

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

if TEST_DATABASE_URL:
    # Settings are read at import time, so configure the environment before importing the app.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["USER_SECRETS_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["USE_GUARDRAIL"] = "false"
    # Point OpenAI at a closed local port: agent runs fail fast without any network traffic.
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9/v1"


@pytest.fixture(scope="session")
def event_loop_policy():
    # psycopg (LangGraph checkpointer) can't use the Proactor loop that Windows uses by default.
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


def pytest_collection_modifyitems(config, items):
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set")
    for item in items:
        item.add_marker(skip)


@pytest.fixture
async def db_engine():
    from sqlalchemy import text

    from app.db.base import Base, engine

    yield engine
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def make_user(db_engine, monkeypatch):
    """Provision a user through the real auth dependency with a faked Firebase token check."""
    from app import dependencies
    from app.db.base import session_scope

    monkeypatch.setattr(dependencies, "_init_firebase_admin", lambda: None)

    async def _make(
        uid: str,
        email: str,
        name: str = "Test User",
        organization_id: str | None = None,
        email_verified: bool = True,
    ):
        monkeypatch.setattr(
            dependencies.auth,
            "verify_id_token",
            lambda token, **_: {"uid": uid, "email": email, "name": name, "email_verified": email_verified},
        )
        creds = dependencies.HTTPAuthorizationCredentials(scheme="Bearer", credentials="fake")
        async with session_scope() as session:
            identity = await dependencies.get_authenticated_user(creds, session)
            return await dependencies.get_current_user(identity, session, organization_id)

    return _make


@pytest.fixture
async def client_for(db_engine):
    """Return an HTTP client authenticated as the given user context."""
    from fastapi import Request
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_authenticated_user, get_current_user
    from app.main import app
    from app.models.user import AuthenticatedUser

    users = {}
    identities = {}
    clients = []

    def _current_user(request: Request):
        return users[request.headers["x-test-user"]]

    def _authenticated_user(request: Request):
        return identities[request.headers["x-test-user"]]

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_authenticated_user] = _authenticated_user

    def _client(user_ctx, email_verified: bool = True):
        users[user_ctx.user.id] = user_ctx
        identities[user_ctx.user.id] = AuthenticatedUser(user=user_ctx.user, email_verified=email_verified)
        c = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"x-test-user": user_ctx.user.id},
        )
        clients.append(c)
        return c

    yield _client
    for c in clients:
        await c.aclose()
    app.dependency_overrides.clear()
