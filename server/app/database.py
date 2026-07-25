from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

# NullPool is a test-suite setting: pooled asyncpg connections bind to the creating event loop,
# which breaks under pytest-asyncio's per-test loops. See Settings.db_nullpool.
_engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
if settings.db_nullpool:
    _engine_kwargs = {"echo": False, "poolclass": NullPool}

engine = create_async_engine(settings.database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
