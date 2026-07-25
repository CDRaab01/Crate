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
