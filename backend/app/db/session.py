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
                    "pool_recycle": settings.DB_POOL_RECYCLE,
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
        _register_engine_listeners(_engine.sync_engine)
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


def _categorize_statement(stmt: str) -> str:
    """Categorize SQL statement safely without exposing parameters or user data."""
    s = stmt.lower()
    if "cosine_distance" in s or "<=>" in s or ("embedding" in s and "document_chunks" in s):
        return "vector_search"
    if "plainto_tsquery" in s or "search_vector" in s or "ts_rank" in s:
        return "keyword_search"
    if "users" in s and ("select" in s or "where" in s):
        return "user_lookup"
    if "organization_memberships" in s or "organizations" in s:
        return "organization_resolution"
    if "knowledge_bases" in s:
        return "knowledge_base_resolution"
    if "conversations" in s:
        return "conversation_lookup"
    if "messages" in s and ("insert" in s or "update" in s or "select" in s):
        return "message_persistence"
    if "documents" in s:
        return "document_metadata"
    return "other"


def _register_engine_listeners(sync_engine) -> None:
    from sqlalchemy import event

    from app.core.tracing import get_current_trace

    # Instrument pool checkout / connection acquisition time
    pool = getattr(sync_engine, "pool", None)
    if pool is not None and not getattr(pool, "_byok_instrumented", False):
        orig_connect = pool.connect

        def instrumented_pool_connect(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return orig_connect(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                trace = get_current_trace()
                if trace is not None:
                    trace.record_db_connection_acquisition(duration_ms)

        pool.connect = instrumented_pool_connect
        pool._byok_instrumented = True

    @event.listens_for(sync_engine, "before_cursor_execute")
    def before_cursor_execute(_conn, _cursor, _statement, _parameters, context, _executemany):
        context._byok_query_t0 = time.perf_counter()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def after_cursor_execute(_conn, _cursor, statement, _parameters, context, _executemany):
        if hasattr(context, "_byok_query_t0"):
            duration_ms = (time.perf_counter() - context._byok_query_t0) * 1000.0
            trace = get_current_trace()
            if trace is not None:
                category = _categorize_statement(statement)
                trace.record_db_query(category, duration_ms)

    @event.listens_for(sync_engine, "handle_error")
    def handle_error(exception_context):
        ctx = getattr(exception_context, "execution_context", None)
        if ctx and hasattr(ctx, "_byok_query_t0"):
            duration_ms = (time.perf_counter() - ctx._byok_query_t0) * 1000.0
            trace = get_current_trace()
            if trace is not None:
                statement = getattr(exception_context, "statement", "") or ""
                category = _categorize_statement(statement)
                trace.record_db_query(f"{category}_error", duration_ms)


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
            "invalid": getattr(pool, "invalidated", lambda: None)()
            if hasattr(pool, "invalidated")
            else None,
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
        trace.record_session_created(1)
        trace.record("db_session_factory_ms", sess_create_ms)
        # pool status snapshot at acquisition
        ps = get_pool_status()
        for k, v in ps.items():
            trace.set_counter(f"pool_{k}", v)

    async with session_factory() as session:
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
            # No explicit session.close(): `async with session_factory()` already
            # closes the session on exit; only record release timing here.
            close_t0 = time.perf_counter()
            if trace:
                trace.record("db_connection_release_ms", (time.perf_counter() - close_t0) * 1000.0)
