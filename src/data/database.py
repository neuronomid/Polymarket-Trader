"""Database engine and session management.

Provides async SQLAlchemy engine and session factory for all database access.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Module-level singletons — initialized via init_db()
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str, echo: bool = False) -> AsyncEngine:
    """Initialize the async database engine and session factory.

    Args:
        database_url: PostgreSQL async connection string
            (e.g. postgresql+asyncpg://user:pass@host:port/db).
        echo: If True, log all SQL statements.
    """
    global _engine, _session_factory

    _engine = create_async_engine(
        database_url,
        echo=echo,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
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
