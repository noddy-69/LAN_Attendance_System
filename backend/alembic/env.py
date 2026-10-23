import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── App imports ───────────────────────────────────────────────────────
# These come after fileConfig() by Alembic convention (E402 is expected here).
# Both imports are from modules that carry no engine-creation side effects:
#   config.py  — pure settings + constants
#   models/base.py — pure SQLAlchemy declarative base
from app.core.config import ASYNCPG_CONNECT_ARGS, settings  # noqa: E402
import app.models  # noqa: E402, F401 — registers all 22 tables on Base.metadata
from app.models.base import Base                             # noqa: E402

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


# ── Helpers ───────────────────────────────────────────────────────────
def _sync_url(async_url: str) -> str:
    """Return a psycopg2-dialect URL for offline SQL generation."""
    return async_url.replace("postgresql+asyncpg://", "postgresql://")


# ── Offline mode (generates SQL without a live DB connection) ─────────
def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(settings.DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (live database via asyncpg) ───────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    async_engine = create_async_engine(
        settings.DATABASE_URL,
        connect_args=ASYNCPG_CONNECT_ARGS,
    )
    async with async_engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await async_engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
