"""
Tests for SQL telemetry accuracy and database metric separation (Task 2).
Verifies:
1. sql_statement_execution_ms measures raw cursor execution time.
2. db_connection_acquisition_ms measures pool acquisition/checkout duration.
3. db_commit_ms measures transaction flush and commit duration.
4. No double-counting or unit mixing across metrics.
5. Error handling and timing attribution on failed SQL statements and commits.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tracing import RequestTrace, get_current_trace, trace_context
from app.db.session import _register_engine_listeners
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService


@pytest.mark.asyncio
async def test_sql_statement_execution_timing_and_counter():
    """Verify cursor execution accurately records queries, timing, and categories without param leakage."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _register_engine_listeners(engine.sync_engine)

    trace = RequestTrace(trace_id="test-sql-1", request_id="req-sql-1")

    with trace_context(trace):
        async with AsyncSession(engine) as session:
            await session.execute(text("CREATE TABLE test_users (id INT, email TEXT)"))
            await session.execute(text("INSERT INTO test_users (id, email) VALUES (1, 'u@test.com')"))
            await session.execute(text("SELECT * FROM test_users WHERE id = 1"))
            await session.commit()

    assert trace.counters.get("db_queries") == 3
    sql_stmt_ms = trace.counters.get("sql_statement_execution_ms", 0.0)
    assert sql_stmt_ms > 0.0
    assert trace.stages.get("sql_statement_execution_ms") == sql_stmt_ms

    # Ensure query categories were assigned
    categories = [q["category"] for q in trace.db_queries]
    assert len(categories) == 3

    summary = trace.to_performance_summary()
    assert summary["latencies"]["sql_statement_execution_ms"] == sql_stmt_ms
    assert summary["counts"]["db_queries"] == 3

    await engine.dispose()


@pytest.mark.asyncio
async def test_db_connection_acquisition_timing_recording():
    """Verify pool connection checkout records duration and increments checkout counter."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _register_engine_listeners(engine.sync_engine)

    trace = RequestTrace(trace_id="test-conn-1", request_id="req-conn-1")

    with trace_context(trace):
        async with AsyncSession(engine) as session:
            await session.execute(text("SELECT 1"))

    assert trace.counters.get("db_pool_checkouts", 0) >= 1
    acq_ms = trace.counters.get("db_connection_acquisition_ms", 0.0)
    assert acq_ms >= 0.0
    assert trace.stages.get("db_connection_acquisition_ms") == acq_ms

    summary = trace.to_performance_summary()
    assert summary["latencies"]["db_connection_acquisition_ms"] == acq_ms
    assert summary["counts"]["db_pool_checkouts"] >= 1

    await engine.dispose()


def test_db_commit_metric_accumulation_and_no_overlap():
    """Verify db_commit_ms accumulates cleanly across multiple commits and does not overlap sql_statement_execution_ms."""
    trace = RequestTrace()
    trace.record_db_query("conversation_lookup", 12.5)
    trace.record_db_query("vector_search", 25.0)

    # 2 distinct commits during lifecycle (e.g. pre-LLM and assistant save)
    trace.record_db_commit(10.0)
    trace.record_db_commit(15.0)

    # Verify distinct counters
    assert trace.counters["db_queries"] == 2
    assert trace.counters["sql_statement_execution_ms"] == 37.5
    assert trace.counters["db_commits"] == 2
    assert trace.counters["db_commit_ms"] == 25.0

    # Verify stage attribution
    assert trace.stages["sql_statement_execution_ms"] == 37.5
    assert trace.stages["db_commit_ms"] == 25.0

    # Verify performance summary separation
    summary = trace.to_performance_summary()
    latencies = summary["latencies"]
    assert latencies["sql_statement_execution_ms"] == 37.5
    assert latencies["db_commit_ms"] == 25.0
    # sql_statement_execution_ms and db_commit_ms are separate, non-overlapping measurements
    assert latencies["sql_statement_execution_ms"] != latencies["db_commit_ms"]

    # Verify export dict structure
    export = trace.to_export_dict()
    assert export["stages"]["database"]["sql_statement_execution_ms"] == 37.5
    assert export["stages"]["database"]["db_commit_ms"] == 25.0
    assert export["stages"]["persistence"]["db_commit_ms"] == 25.0


@pytest.mark.asyncio
async def test_sql_error_statement_timing_attribution():
    """Verify that when a SQL query fails, handle_error records the query timing and category."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _register_engine_listeners(engine.sync_engine)

    trace = RequestTrace(trace_id="test-err-sql", request_id="req-err-sql")

    with trace_context(trace):
        async with AsyncSession(engine) as session:
            try:
                await session.execute(text("SELECT * FROM non_existent_table_xyz_123"))
            except (ProgrammingError, OperationalError):
                pass

    # handle_error should record the failed query
    assert trace.counters.get("db_queries") == 1
    assert any("error" in q["category"] for q in trace.db_queries)
    assert trace.counters.get("sql_statement_execution_ms", 0.0) > 0.0

    await engine.dispose()


@pytest.mark.asyncio
async def test_rag_pipeline_sql_telemetry_attribution(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify full RAG pipeline accurately tracks sql_statement_execution_ms, db_commits, and checkouts."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Test telemetry query",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-rag-telemetry", request_id="req-rag-telemetry")

    with trace_context(trace):
        resp = await rag_service.generate(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )

    assert resp.conversation_id is not None
    summary = trace.to_performance_summary()
    latencies = summary["latencies"]
    counts = summary["counts"]

    # 1. Commits must be tracked: 2 commits in non-streaming (pre-LLM user message commit + post-LLM assistant commit)
    assert counts.get("db_commits") >= 2
    assert latencies.get("db_commit_ms", 0.0) > 0.0

    # 2. Database latency must be present
    assert latencies.get("database_latency_ms", 0.0) > 0.0

    # 3. Export dict must contain separate database breakdown
    export = trace.to_export_dict()
    assert "database" in export["stages"]
    assert export["stages"]["database"]["db_commit_ms"] > 0.0
