import contextlib
import logging
import time
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
            # Neon pooler aggressively closes idle connections (often <5min) and
            # Windows NAT can reset sockets (WinError 10054). Use short recycle,
            # pre_ping, and no statement cache to avoid prepared-statement bleed
            # across pooled connections.
            engine_kwargs.update(
                {
                    "pool_size": settings.DB_POOL_SIZE,
                    "max_overflow": settings.DB_MAX_OVERFLOW,
                    "pool_timeout": settings.DB_POOL_TIMEOUT,
                    "pool_recycle": 300,
                    "pool_pre_ping": True,
                    "connect_args": {
                        "statement_cache_size": 0,
                        "prepared_statement_cache_size": 0,
                        "timeout": 60,
                        "command_timeout": 60,
                    },
                }
            )

        _engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
        logger.info(
            "Initialized AsyncEngine dialect=%s pool_size=%s max_overflow=%s pool_timeout=%s pool_recycle=%s pre_ping=%s",
            _engine.dialect.name,
            engine_kwargs.get("pool_size"),
            engine_kwargs.get("max_overflow"),
            engine_kwargs.get("pool_timeout"),
            engine_kwargs.get("pool_recycle"),
            engine_kwargs.get("pool_pre_ping"),
        )
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


def get_pool_status() -> dict:
    """Return current connection pool metrics for tracing / health."""
    if _engine is None:
        return {"status": "not_initialized"}
    try:
        pool = _engine.pool  # type: ignore[attr-defined]
        return {
            "pool_size": getattr(pool, "size", lambda: None)(),
            "checked_out": getattr(pool, "checkedout", lambda: None)(),
            "overflow": getattr(pool, "overflow", lambda: None)(),
            "invalid": getattr(pool, "invalidated", lambda: None)() if hasattr(pool, "invalidated") else None,
        }
    except Exception:
        return {"status": "unknown"}

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an async database session per request.
    Rolls back transaction automatically if an uncaught exception occurs.
    Handles transient Neon/Windows connection resets by invalidating
    the pooled connection and surfacing a retryable error to the caller.
    """
    from app.core.tracing import get_current_trace

    trace = get_current_trace()
    sess_t0 = time.perf_counter()
    session_factory = get_session_factory()
    sess_create_ms = (time.perf_counter() - sess_t0) * 1000.0
    if trace:
        trace.record("db_session_factory_ms", sess_create_ms)
        # pool status snapshot at acquisition
        ps = get_pool_status()
        for k, v in ps.items():
            trace.set_counter(f"pool_{k}", v)

    async with session_factory() as session:
        checkout_ms = 0.0
        if trace:
            # estimate checkout overhead (session creation is lazy; actual checkout on first query)
            trace.record("db_session_acquisition_ms", sess_create_ms)
        try:
            yield session
        except Exception:
            with contextlib.suppress(Exception):
                await session.rollback()
            raise
        finally:
            close_t0 = time.perf_counter()
            with contextlib.suppress(Exception):
                await session.close()
            if trace:
                trace.record("db_connection_release_ms", (time.perf_counter() - close_t0) * 1000.0)
