import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger("app.db.session")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create the global async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        # Engine kwargs configuration
        engine_kwargs: dict[str, object] = {
            "echo": False,
            "future": True,
        }

        # PostgreSQL specific pool settings (SQLite for tests doesn't use pool_size)
        if "postgresql" in settings.DATABASE_URL:
            engine_kwargs.update(
                {
                    "pool_size": settings.DB_POOL_SIZE,
                    "max_overflow": settings.DB_MAX_OVERFLOW,
                    "pool_timeout": settings.DB_POOL_TIMEOUT,
                    "pool_pre_ping": True,
                }
            )

        _engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
        logger.info("Initialized AsyncEngine with database URL dialect: %s", _engine.dialect.name)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async sessionmaker."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _session_factory


async def close_db_engine() -> None:
    """Cleanly dispose the database engine on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        logger.info("Disposing AsyncEngine connection pool...")
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an async database session per request.
    Rolls back transaction automatically if an uncaught exception occurs.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
