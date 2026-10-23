"""
Test fixtures — synchronous SQLAlchemy session against the real PostgreSQL DB.

Each test gets its own database transaction that is rolled back on teardown,
so tests are fully isolated and leave no data behind.

The DATABASE_URL is read from the environment (set by docker-compose or .env).
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _sync_url() -> str:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://attendance_user:attendance_local_pass@postgres:5432/attendance",
    )
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(_sync_url(), pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """
    Yield a Session wrapped in a transaction that is rolled back after the test.
    The session flushes automatically on each query so INSERTs are visible
    within the same connection without a COMMIT.
    """
    connection = db_engine.connect()
    transaction = connection.begin()

    Session = sessionmaker(bind=connection, expire_on_commit=False)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
