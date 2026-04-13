"""Test fixtures shared across all test modules.

Provides structlog setup and an in-memory SQLite database with all tables
created for testing. Uses JSON type mapping to handle PostgreSQL-specific
JSONB columns in SQLite.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import JSON, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from data.base import Base

# Import all models to register them
import data  # noqa: F401


# Configure structlog once at import time so all tests have a working logger.
# cache_logger_on_first_use must be False to avoid capturing pytest's capsys file.
import structlog

import io

_STRUCTLOG_CONFIG = dict(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    context_class=dict,
    # Use a fresh StringIO so we never write to a closed capsys CaptureIO file.
    logger_factory=structlog.PrintLoggerFactory(file=io.StringIO()),
    cache_logger_on_first_use=False,
)

structlog.configure(**_STRUCTLOG_CONFIG)


@pytest.fixture(autouse=True)
def _reset_structlog():
    """Reset structlog config after each test.

    Tests like test_logging.py call setup_logging() which reconfigures structlog
    to use sys.stdout (pytest's CaptureIO). After the test, CaptureIO closes but
    structlog's factory still references it. This fixture restores safe config.
    """
    yield
    structlog.configure(**{**_STRUCTLOG_CONFIG, "logger_factory": structlog.PrintLoggerFactory(file=io.StringIO())})


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create an async SQLite engine for testing.

    Maps JSONB → JSON so SQLite can handle PostgreSQL-specific types.
    """
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # Enable FK enforcement for SQLite
    @event.listens_for(eng.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Map PostgreSQL JSONB to generic JSON for SQLite
    # We need to modify the metadata to replace JSONB with JSON before table creation
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    """Create a fresh async session per test, with rollback after each test."""
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as sess:
        async with sess.begin():
            yield sess
            await sess.rollback()
