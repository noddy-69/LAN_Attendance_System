from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import ASYNCPG_CONNECT_ARGS, settings

# ── Engine ────────────────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=20,       # max_employees=20 → need 20 concurrent connections under peak load
    max_overflow=5,     # small headroom for admin/celery tasks above employee peak
    pool_pre_ping=True,  # verify connection is alive before using it from pool
    pool_recycle=3600,   # recycle connections every hour; prevents stale-socket errors
    pool_timeout=30,     # raise after 30 s instead of queuing indefinitely
    connect_args=ASYNCPG_CONNECT_ARGS,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # prevents implicit lazy-loads on committed objects in async context
)


# ── FastAPI dependency ────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session, commit on clean exit, roll back on any exception."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
