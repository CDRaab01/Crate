import asyncio
import os

# Must be set before any `app.*` import: the engine is built at app.database import time.
# NullPool keeps pooled asyncpg connections from binding to a single event loop (the suite's
# known local-pytest failure mode).
os.environ.setdefault("DB_NULLPOOL", "true")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, engine
from app.limiter import limiter
from app.main import app

# Disable rate limiting for the test suite.
limiter.enabled = False


@pytest.fixture(scope="session")
def event_loop():
    """Share a single event loop across the whole test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_tables():
    """Ensure all tables exist before any test runs (safe to call after alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(client):
    """HTTP client pre-authenticated as a fresh unique test user.

    SSO-only app: there is no register endpoint, so the user row is created directly and a
    session token minted with the app's own signer — exactly what /auth/suite would do."""
    import uuid

    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.security import create_access_token

    async with AsyncSessionLocal() as db:
        user = User(name="Test Seller", email=f"test_{uuid.uuid4().hex[:8]}@crate.test")
        db.add(user)
        await db.commit()
        await db.refresh(user)

    client.headers["Authorization"] = f"Bearer {create_access_token(str(user.id))}"
    client.user_id = user.id
    client.email = user.email  # scripts/ resolve the user by email, not id
    return client
