"""Evaluation suite for TracePilot Milestone 3A: Evidence Hybrid Retrieval.

Tests:
1. Synthetic incident dataset with realistic timeline and distractor events.
2. Retrieval evaluation metrics: Recall@K and MRR across 4 query classes.
3. Multi-channel RRF provenance (lexical, semantic, recency, hybrid).
4. Strict tenant isolation (org-level and incident-level at DB query boundary).
5. Deterministic ranking stability under identical repeated queries.
6. Honest empty results on irrelevant queries.
7. Comparison: lexical-only vs semantic-only vs hybrid.
8. Embedding provider failure graceful degradation (lexical fallback).
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import EvidenceEvent
from app.models.incident import Incident
from app.models.organization import Organization
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.providers import get_embedding_provider
from app.services.investigations.evidence_embedding import (
    build_evidence_embedding_text,
    generate_evidence_embedding,
)
from app.services.investigations.retrieval import InvestigationRetrievalService


@pytest.fixture
async def synthetic_incident_setup(db_session: AsyncSession):
    """Build synthetic incident fixture from Milestone 3A specification."""
    org = Organization(name="Eval Org", slug="eval-org")
    db_session.add(org)
    await db_session.flush()

    incident = Incident(
        organization_id=org.id,
        title="Payment API 502 Outage",
        description="Spike in 502 errors following payment-api deployment",
        severity="critical",
        service_name="payment-api",
        environment="production",
    )
    db_session.add(incident)
    await db_session.flush()

    # Synthetic Timeline & Distractors
    raw_events = [
        # Target 1: Deployment before outage
        (
            "ev_deploy",
            "deployment",
            "deployment.completed",
            datetime(2026, 10, 4, 14, 2, 10, tzinfo=UTC),
            "Deployment v2.4.1 completed for payment-api service",
            {"service": "payment-api", "version": "v2.4.1"},
            "argocd://deploys/payment-api-v2.4.1",
        ),
        # Target 2: HTTP 502 alert
        (
            "ev_alert",
            "alert",
            "alert.triggered",
            datetime(2026, 10, 4, 14, 3, 4, tzinfo=UTC),
            "HTTP 502 rate exceeded 5% on payment-api",
            {"service": "payment-api", "status_code": 502},
            "pagerduty://alerts/PD-1029",
        ),
        # Target 3: DB connection pool exhaustion
        (
            "ev_db",
            "log",
            "database.connection_timeout",
            datetime(2026, 10, 4, 14, 3, 12, tzinfo=UTC),
            "Database connection pool exhausted: 100/100 connections active",
            {"service": "payment-api", "pool_size": 100},
            "k8s://pods/payment-api-7b8f/log",
        ),
        # Distractor 1: Unrelated deployment 6 hours earlier
        (
            "ev_dist_auth_deploy",
            "deployment",
            "deployment.completed",
            datetime(2026, 10, 4, 8, 15, 0, tzinfo=UTC),
            "Deployment v1.1.0 completed for auth-service",
            {"service": "auth-service", "version": "v1.1.0"},
            "argocd://deploys/auth-v1.1.0",
        ),
        # Distractor 2: Old DB warning on unrelated read replica
        (
            "ev_dist_replica_warn",
            "log",
            "database.warning",
            datetime(2026, 10, 4, 9, 30, 0, tzinfo=UTC),
            "Slow query detected on read replica (>250ms)",
            {"service": "inventory-db", "duration_ms": 260},
            "datadog://logs/replica-02",
        ),
        # Distractor 3: Health check passed
        (
            "ev_dist_health_ok",
            "metric",
            "health.check",
            datetime(2026, 10, 4, 13, 55, 0, tzinfo=UTC),
            "Periodic synthetic health check passed for payments",
            {"service": "payment-api", "status": "ok"},
            "datadog://synthetics/check-1",
        ),
        # Distractor 4: Unrelated Git commit
        (
            "ev_dist_git_push",
            "git",
            "git.push",
            datetime(2026, 10, 4, 14, 1, 0, tzinfo=UTC),
            "Commit pushed to main by dev: chore: update README",
            {"author": "alice", "repo": "payment-api"},
            "github://commits/7f83a1",
        ),
        # Distractor 5: Routine unrelated service log
        (
            "ev_dist_user_log",
            "log",
            "app.info",
            datetime(2026, 10, 4, 14, 5, 0, tzinfo=UTC),
            "User profile fetched successfully for user_987",
            {"service": "user-service"},
            "k8s://pods/user-svc-99/log",
        ),
    ]

    embed_provider = get_embedding_provider()
    events_map: dict[str, EvidenceEvent] = {}

    for (
        name,
        src_type,
        ev_type,
        ts,
        summary,
        payload,
        ref,
    ) in raw_events:
        text = build_evidence_embedding_text(
            source_type=src_type,
            event_type=ev_type,
            summary=summary,
            normalized_payload=payload,
            source_reference=ref,
        )
        vec = await generate_evidence_embedding(text, provider=embed_provider)
        ev = EvidenceEvent(
            incident_id=incident.id,
            organization_id=org.id,
            source_type=src_type,
            event_type=ev_type,
            event_timestamp=ts,
            summary=summary,
            normalized_payload=payload,
            source_reference=ref,
            embedding=vec,
            embedding_model=embed_provider.model_name if vec else None,
            embedded_at=datetime.now(UTC) if vec else None,
        )
        db_session.add(ev)
        events_map[name] = ev

    await db_session.commit()
    for ev in events_map.values():
        await db_session.refresh(ev)

    return {
        "org": org,
        "incident": incident,
        "events": events_map,
    }


@pytest.mark.asyncio
async def test_hybrid_retrieval_recall_and_mrr(
    db_session: AsyncSession,
    synthetic_incident_setup: dict,
):
    """Verify Recall@K and MRR on the 4 evaluation queries."""
    org = synthetic_incident_setup["org"]
    inc = synthetic_incident_setup["incident"]
    evs = synthetic_incident_setup["events"]

    test_cases = [
        # Query 1: DB connection failure -> ev_db must be rank 1
        ("database connection failure", {evs["ev_db"].id}, 1),
        # Query 2: "what changed before the 502 errors" -> 502 alert (rank 1) or deployment
        ("what changed before the 502 errors", {evs["ev_alert"].id, evs["ev_deploy"].id}, 1),
        # Query 3: "deployment related to payment-api" -> ev_deploy rank 1
        ("deployment related to payment-api", {evs["ev_deploy"].id}, 1),
        # Query 4: "connection pool exhaustion" -> ev_db rank 1
        ("connection pool exhaustion", {evs["ev_db"].id}, 1),
    ]

    reciprocal_ranks = []
    top3_hits = 0

    for query, expected_ids, max_acceptable_rank in test_cases:
        results = await InvestigationRetrievalService.retrieve_evidence(
            session=db_session,
            organization_id=org.id,
            incident_id=inc.id,
            query=query,
            limit=5,
        )
        assert len(results) > 0

        # Find best rank among expected targets
        target_rank = None
        for r in results:
            if r.event.id in expected_ids:
                target_rank = r.rank
                break

        assert target_rank is not None, (
            f"Expected target in {expected_ids} not in top 5 for '{query}'"
        )
        assert target_rank <= max_acceptable_rank, (
            f"Expected rank <= {max_acceptable_rank}, got {target_rank} for '{query}'"
        )

        reciprocal_ranks.append(1.0 / target_rank)
        if target_rank <= 3:
            top3_hits += 1

    # Metrics computation
    recall_at_3 = top3_hits / len(test_cases)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)

    assert recall_at_3 == 1.0, f"Recall@3 was {recall_at_3}, expected 1.0"
    assert mrr >= 0.8, f"MRR was {mrr}, expected >= 0.8"


@pytest.mark.asyncio
async def test_retrieval_sources_and_provenance(
    db_session: AsyncSession,
    synthetic_incident_setup: dict,
):
    """Verify retrieved candidates contain rich provenance and retrieval_sources."""
    org = synthetic_incident_setup["org"]
    inc = synthetic_incident_setup["incident"]

    results = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id=inc.id,
        query="payment-api 502 alert",
        limit=5,
    )

    assert len(results) > 0
    for r in results:
        assert isinstance(r.retrieval_sources, list)
        assert len(r.retrieval_sources) >= 1
        assert set(r.retrieval_sources).issubset({"lexical", "semantic", "recency"})
        assert r.retrieval_method in {"hybrid", "semantic", "lexical", "recency"}
        assert r.rank >= 1
        assert r.retrieval_score > 0.0
        assert r.evidence_event_id == r.event.id
        assert r.summary == r.event.summary
        assert r.source_type == r.event.source_type


@pytest.mark.asyncio
async def test_tenant_and_incident_isolation(
    db_session: AsyncSession,
    synthetic_incident_setup: dict,
):
    """Verify cross-tenant and cross-incident queries return strictly zero records."""
    org = synthetic_incident_setup["org"]
    inc = synthetic_incident_setup["incident"]

    # 1. Another organization querying this incident
    other_org = Organization(name="Attacker Org", slug="attacker-org")
    db_session.add(other_org)
    await db_session.commit()

    cross_org_results = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=other_org.id,
        incident_id=inc.id,
        query="database connection pool",
        limit=10,
    )
    assert cross_org_results == []

    # 2. Same organization querying a non-existent incident
    cross_inc_results = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id="00000000-0000-0000-0000-000000000000",
        query="database connection pool",
        limit=10,
    )
    assert cross_inc_results == []


@pytest.mark.asyncio
async def test_determinism_under_identical_queries(
    db_session: AsyncSession,
    synthetic_incident_setup: dict,
):
    """Verify identical queries return exact same order, ranks, and scores."""
    org = synthetic_incident_setup["org"]
    inc = synthetic_incident_setup["incident"]

    run_1 = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id=inc.id,
        query="database connection pool exhaustion",
        limit=5,
    )
    run_2 = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id=inc.id,
        query="database connection pool exhaustion",
        limit=5,
    )

    assert len(run_1) == len(run_2)
    for r1, r2 in zip(run_1, run_2, strict=True):
        assert r1.event.id == r2.event.id
        assert r1.rank == r2.rank
        assert r1.retrieval_score == r2.retrieval_score
        assert r1.retrieval_sources == r2.retrieval_sources


@pytest.mark.asyncio
async def test_empty_results_on_empty_incident(
    db_session: AsyncSession,
):
    """Verify empty incident returns empty list safely without fabrication."""
    org = Organization(name="Empty Org", slug="empty-org")
    db_session.add(org)
    await db_session.flush()

    empty_inc = Incident(organization_id=org.id, title="Empty Incident", severity="low")
    db_session.add(empty_inc)
    await db_session.commit()

    results = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id=empty_inc.id,
        query="any query",
        limit=10,
    )
    assert results == []


@pytest.mark.asyncio
async def test_compare_lexical_semantic_and_hybrid(
    db_session: AsyncSession,
    synthetic_incident_setup: dict,
):
    """Compare lexical-only vs semantic-only vs hybrid retrieval modes."""
    org = synthetic_incident_setup["org"]
    inc = synthetic_incident_setup["incident"]
    evs = synthetic_incident_setup["events"]

    # Natural language query with semantic meaning but few shared keywords with deployment
    query = "what changed right before the 502 errors started"

    lex_results = await InvestigationRetrievalService.retrieve_evidence_lexical_only(
        session=db_session,
        organization_id=org.id,
        incident_id=inc.id,
        query=query,
        limit=5,
    )
    assert len(lex_results) > 0

    sem_results = await InvestigationRetrievalService.retrieve_evidence_semantic_only(
        session=db_session,
        organization_id=org.id,
        incident_id=inc.id,
        query=query,
        limit=5,
    )
    hybrid_results = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id=inc.id,
        query=query,
        limit=5,
    )

    # In semantic search, deployment and alert are highly ranked
    sem_ids = [r.event.id for r in sem_results[:3]]
    assert evs["ev_deploy"].id in sem_ids or evs["ev_alert"].id in sem_ids

    # In hybrid search, the fused ranking prioritizes both deployment and alert
    hybrid_ids = [r.event.id for r in hybrid_results[:5]]
    assert evs["ev_deploy"].id in hybrid_ids or evs["ev_alert"].id in hybrid_ids


@pytest.mark.asyncio
async def test_embedding_provider_failure_degrades_to_lexical(
    db_session: AsyncSession,
    synthetic_incident_setup: dict,
):
    """Verify when embedding provider fails, hybrid retrieval falls back gracefully."""
    org = synthetic_incident_setup["org"]
    inc = synthetic_incident_setup["incident"]
    evs = synthetic_incident_setup["events"]

    # Faulty provider raising exception
    faulty_provider = MagicMock(spec=BaseEmbeddingProvider)
    faulty_provider.embed_query.side_effect = TimeoutError("Embedding provider timed out")

    # Retrieval should not raise: falls back to lexical + recency
    results = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id=inc.id,
        query="database connection pool",
        limit=5,
        provider=faulty_provider,
    )

    assert len(results) > 0
    # Top result should still be ev_db via lexical match!
    assert results[0].event.id == evs["ev_db"].id
    # Semantic was not in sources due to provider timeout
    assert "semantic" not in results[0].retrieval_sources
    assert "lexical" in results[0].retrieval_sources
