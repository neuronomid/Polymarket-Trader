"""Database engine and session management.

Provides async SQLAlchemy engine and session factory for all database access.
Supports both PostgreSQL (production) and SQLite (paper mode / development).
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Module-level singletons — initialized via init_db()
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _remap_jsonb_for_sqlite() -> None:
    """Remap PostgreSQL JSONB columns to generic JSON for SQLite compatibility."""
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import JSON

    from data.base import Base

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


async def init_db(database_url: str, echo: bool = False) -> AsyncEngine:
    """Initialize the async database engine and session factory.

    Args:
        database_url: Async connection string. Supported formats:
            - postgresql+asyncpg://user:pass@host:port/db
            - sqlite+aiosqlite:///path/to/db.sqlite (paper mode)
        echo: If True, log all SQL statements.
    """
    global _engine, _session_factory

    is_sqlite = "sqlite" in database_url

    engine_kwargs: dict = {
        "echo": echo,
    }

    if is_sqlite:
        # SQLite doesn't support connection pooling the same way
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        # Remap JSONB → JSON for SQLite
        _remap_jsonb_for_sqlite()
    else:
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20
        engine_kwargs["pool_pre_ping"] = True

    _engine = create_async_engine(database_url, **engine_kwargs)

    # Enable foreign keys for SQLite
    if is_sqlite:
        @event.listens_for(_engine.sync_engine, "connect")
        def _enable_sqlite_fks(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Auto-create tables for SQLite (no Alembic needed for paper mode)
    if is_sqlite:
        # Import all models so Base.metadata is populated
        import data.models  # noqa: F401

        async with _engine.begin() as conn:
            from data.base import Base
            await conn.run_sync(Base.metadata.create_all)

    return _engine


def get_engine() -> AsyncEngine:
    """Return the initialized engine; raises if init_db() was not called."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory; raises if init_db() was not called."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


async def get_session() -> AsyncSession:
    """Create a new async session from the factory."""
    factory = get_session_factory()
    return factory()


async def close_db() -> None:
    """Dispose the engine and release all connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
