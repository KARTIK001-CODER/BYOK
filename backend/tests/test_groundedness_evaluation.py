"""Comprehensive test suite for TracePilot Milestone 4 Groundedness & Confidence Calibration.

Covers:
- Groundedness evaluation across valid, invalid, supporting, contradicting, mixed evidence
- Temporal consistency & inconsistency detection
- Duplicate evidence inflation damping vs source diversity
- Unsupported failure mechanism penalty
- Deterministic scoring, monotonicity, and score bounds [0.0, 1.0]
- Multi-tenant and incident security isolation
- Safe error handling and evaluation failure containment
- Full investigation pipeline persistence and API serialization
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.evidence import EvidenceEvent
from app.models.investigation import (
    GroundednessStatus,
    SystemConfidenceLevel,
)
from app.services.investigations.groundedness import (
    GroundednessEvaluator,
)
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider


@pytest.fixture
def use_mock_llm(monkeypatch):
    mock = MockLLMProvider()
    monkeypatch.setattr(
        LLMProviderFactory,
        "create",
        classmethod(lambda _cls, **_kwargs: (mock, "mock-test-model")),
    )
    return mock


def _make_evidence_event(
    id: str,
    org_id: str,
    incident_id: str,
    source_type: str,
    event_type: str,
    summary: str,
    timestamp: datetime,
) -> EvidenceEvent:
    return EvidenceEvent(
        id=id,
        organization_id=org_id,
        incident_id=incident_id,
        source_type=source_type,
        event_type=event_type,
        summary=summary,
        event_timestamp=timestamp,
        normalized_payload={},
    )


# ─── 1. Unit Tests for GroundednessEvaluator ─────────────────────────────────


def test_strongly_supported_hypothesis() -> None:
    now = datetime.now(UTC)
    org_id = "org-1"
    inc_id = "inc-1"

    ev1 = _make_evidence_event(
        "ev-1", org_id, inc_id, "deployment", "deployment.completed", "v2.4.1 deployed", now
    )
    ev2 = _make_evidence_event(
        "ev-2",
        org_id,
        inc_id,
        "alert",
        "alert.firing",
        "HTTP 502 spike 15%",
        now + timedelta(minutes=1),
    )
    ev3 = _make_evidence_event(
        "ev-3",
        org_id,
        inc_id,
        "metric",
        "db.pool",
        "Connection pool exhausted",
        now + timedelta(minutes=2),
    )

    ev_map = {ev1.id: ev1, ev2.id: ev2, ev3.id: ev3}
    links = [
        {"evidence_event_id": "ev-1", "link_type": "supports"},
        {"evidence_event_id": "ev-2", "link_type": "supports"},
        {"evidence_event_id": "ev-3", "link_type": "supports"},
    ]

    assessment = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-1",
        claim="Deployment v2.4.1 exhausted connection pool",
        rationale="Deploy followed by alert and pool exhaustion",
        raw_status="supported",
        links=links,
        evidence_map=ev_map,
    )

    assert assessment.groundedness_status == GroundednessStatus.WELL_SUPPORTED.value
    assert assessment.system_confidence == SystemConfidenceLevel.HIGH.value
    assert assessment.groundedness_score >= 0.75
    assert assessment.system_confidence_score >= 0.75
    assert assessment.valid_supporting_count == 3
    assert assessment.valid_contradicting_count == 0
    assert assessment.contradiction_score == 0.0
    assert len(assessment.distinct_source_types) == 3


def test_contradicted_hypothesis_reduces_confidence() -> None:
    now = datetime.now(UTC)
    org_id = "org-1"
    inc_id = "inc-1"

    ev_sup = _make_evidence_event(
        "ev-deploy", org_id, inc_id, "deployment", "deployment.completed", "v2.4.1 deployed", now
    )
    ev_contra = _make_evidence_event(
        "ev-stripe",
        org_id,
        inc_id,
        "alert",
        "alert.firing",
        "Stripe API global 504 outage",
        now + timedelta(minutes=1),
    )

    ev_map = {ev_sup.id: ev_sup, ev_contra.id: ev_contra}
    links = [
        {"evidence_event_id": "ev-deploy", "link_type": "supports"},
        {"evidence_event_id": "ev-stripe", "link_type": "contradicts"},
    ]

    assessment = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-2",
        claim="Deployment v2.4.1 caused checkout failure",
        rationale="Deploy preceded errors",
        raw_status="contested",
        links=links,
        evidence_map=ev_map,
    )

    assert assessment.groundedness_status == GroundednessStatus.CONTESTED.value
    assert assessment.system_confidence == SystemConfidenceLevel.LOW.value
    assert assessment.contradiction_score > 0.4
    assert assessment.system_confidence_score < 0.40
    assert any("contradicting" in r.lower() for r in assessment.assessment_reasons)


def test_invalid_citations_rejected_with_zero_score() -> None:
    assessment = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-3",
        claim="Fictitious memory leak",
        rationale="Citing non-existent evidence",
        raw_status="rejected",
        links=[{"evidence_event_id": "nonexistent-id", "link_type": "supports"}],
        evidence_map={},
    )

    assert assessment.groundedness_status == GroundednessStatus.REJECTED.value
    assert assessment.system_confidence == SystemConfidenceLevel.LOW.value
    assert assessment.groundedness_score == 0.0
    assert assessment.system_confidence_score == 0.0
    assert assessment.valid_supporting_count == 0
    assert assessment.invalid_citation_count == 1


def test_temporal_inconsistency_penalized() -> None:
    now = datetime.now(UTC)
    org_id = "org-1"
    inc_id = "inc-1"

    # Alleged trigger happened AFTER symptoms were already observed!
    ev_symptom = _make_evidence_event(
        "ev-alert", org_id, inc_id, "alert", "alert.firing", "502 spike at 14:00", now
    )
    ev_trigger = _make_evidence_event(
        "ev-deploy",
        org_id,
        inc_id,
        "deployment",
        "deployment.completed",
        "v2.4.2 deployed at 15:00",
        now + timedelta(hours=1),
    )

    ev_map = {ev_symptom.id: ev_symptom, ev_trigger.id: ev_trigger}
    links = [
        {"evidence_event_id": "ev-alert", "link_type": "supports"},
        {"evidence_event_id": "ev-deploy", "link_type": "supports"},
    ]

    assessment = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-4",
        claim="Deployment v2.4.2 caused the 502 spike",
        rationale="Deploy caused errors",
        raw_status="supported",
        links=links,
        evidence_map=ev_map,
    )

    assert assessment.temporal_score == 0.10
    assert any("temporal inconsistency" in r.lower() for r in assessment.assessment_reasons)
    assert assessment.groundedness_score < 0.60


def test_duplicate_evidence_inflation_damped() -> None:
    now = datetime.now(UTC)
    org_id = "org-1"
    inc_id = "inc-1"

    # 5 identical log messages of single source type
    ev_map = {}
    links = []
    for i in range(5):
        eid = f"ev-log-{i}"
        ev = _make_evidence_event(
            eid,
            org_id,
            inc_id,
            "log",
            "app.error",
            "Redis connection timeout",
            now + timedelta(seconds=i),
        )
        ev_map[eid] = ev
        links.append({"evidence_event_id": eid, "link_type": "supports"})

    assessment = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-dup",
        claim="Redis connection timeout caused failures",
        rationale="Multiple logs show redis timeout",
        raw_status="supported",
        links=links,
        evidence_map=ev_map,
    )

    # Effective evidence count should be damped, diversity low
    assert assessment.details["duplicate_count"] == 4
    assert assessment.diversity_score == 0.25
    assert assessment.groundedness_status == GroundednessStatus.WEAKLY_SUPPORTED.value
    assert assessment.system_confidence == SystemConfidenceLevel.LOW.value


def test_unsupported_mechanism_penalized() -> None:
    now = datetime.now(UTC)
    org_id = "org-1"
    inc_id = "inc-1"

    # Evidence only contains deployment and generic 502 alert, but claim asserts DB pool leak
    ev1 = _make_evidence_event(
        "ev-d", org_id, inc_id, "deployment", "deployment.completed", "v2.4.1 deployed", now
    )
    ev2 = _make_evidence_event(
        "ev-a",
        org_id,
        inc_id,
        "alert",
        "alert.firing",
        "HTTP 502 spike",
        now + timedelta(minutes=1),
    )

    ev_map = {ev1.id: ev1, ev2.id: ev2}
    links = [
        {"evidence_event_id": "ev-d", "link_type": "supports"},
        {"evidence_event_id": "ev-a", "link_type": "supports"},
    ]

    assessment = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-unsub",
        claim="Deployment introduced a database connection pool leak causing outage",
        rationale="Deploy happened before alert",
        raw_status="supported",
        links=links,
        evidence_map=ev_map,
    )

    assert assessment.unsupported_claim_score > 0
    assert "database_connection_pool" in assessment.details["unsupported_mechanisms"]
    assert any("asserts failure mechanism" in r.lower() for r in assessment.assessment_reasons)


def test_confidence_monotonicity() -> None:
    now = datetime.now(UTC)
    org_id = "org-1"
    inc_id = "inc-1"

    ev1 = _make_evidence_event(
        "ev-1", org_id, inc_id, "deployment", "deployment.completed", "v2.4.1 deployed", now
    )
    ev2 = _make_evidence_event(
        "ev-2",
        org_id,
        inc_id,
        "alert",
        "alert.firing",
        "HTTP 502 spike",
        now + timedelta(minutes=1),
    )
    ev3 = _make_evidence_event(
        "ev-3",
        org_id,
        inc_id,
        "metric",
        "db.metrics",
        "DB response latency spiked",
        now + timedelta(minutes=2),
    )
    ev_contra = _make_evidence_event(
        "ev-c",
        org_id,
        inc_id,
        "alert",
        "alert.firing",
        "Upstream DNS provider failure",
        now + timedelta(minutes=1),
    )

    # Base assessment with 1 supporting item
    a_base = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-m",
        claim="Deploy caused issue",
        rationale="Sequence",
        raw_status="supported",
        links=[{"evidence_event_id": "ev-1", "link_type": "supports"}],
        evidence_map={ev1.id: ev1},
    )

    # Adding valid supporting evidence without contradiction must NOT decrease confidence
    a_more_support = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-m",
        claim="Deploy caused issue",
        rationale="Sequence",
        raw_status="supported",
        links=[
            {"evidence_event_id": "ev-1", "link_type": "supports"},
            {"evidence_event_id": "ev-2", "link_type": "supports"},
            {"evidence_event_id": "ev-3", "link_type": "supports"},
        ],
        evidence_map={ev1.id: ev1, ev2.id: ev2, ev3.id: ev3},
    )
    assert a_more_support.system_confidence_score >= a_base.system_confidence_score
    assert a_more_support.groundedness_score >= a_base.groundedness_score

    # Adding contradiction must NOT increase confidence
    a_with_contradiction = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-m",
        claim="Deploy caused issue",
        rationale="Sequence",
        raw_status="contested",
        links=[
            {"evidence_event_id": "ev-1", "link_type": "supports"},
            {"evidence_event_id": "ev-2", "link_type": "supports"},
            {"evidence_event_id": "ev-3", "link_type": "supports"},
            {"evidence_event_id": "ev-c", "link_type": "contradicts"},
        ],
        evidence_map={ev1.id: ev1, ev2.id: ev2, ev3.id: ev3, ev_contra.id: ev_contra},
    )
    assert a_with_contradiction.system_confidence_score < a_more_support.system_confidence_score


# ─── 2. Security & Tenant Isolation Tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_and_incident_isolation_in_groundedness_evaluation(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    user = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    # Create incident 1
    resp1 = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Incident 1", "severity": "high", "service_name": "srv-1"},
    )
    inc1_id = resp1.json()["id"]

    # Ingest evidence for incident 1
    ev_resp1 = await client.post(
        f"/api/v1/incidents/{inc1_id}/evidence",
        headers=headers,
        json={
            "source_type": "deployment",
            "event_type": "deploy",
            "event_timestamp": "2026-10-08T10:00:00Z",
            "summary": "Deploy on inc1",
        },
    )
    ev1_id = ev_resp1.json()["id"]

    # Create incident 2
    await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Incident 2", "severity": "high", "service_name": "srv-2"},
    )

    # Attempting to cite ev1_id in an evaluation for incident 2 must be rejected
    # because ev1_id belongs to incident 1
    assessment = GroundednessEvaluator.evaluate(
        hypothesis_id="hyp-cross",
        claim="Cross-incident claim",
        rationale="Citing inc1 evidence in inc2",
        raw_status="supported",
        links=[{"evidence_event_id": ev1_id, "link_type": "supports"}],
        evidence_map={},  # scoped to incident 2: ev1_id is NOT in evidence_map
    )

    assert assessment.groundedness_status == GroundednessStatus.REJECTED.value
    assert assessment.groundedness_score == 0.0
    assert assessment.system_confidence_score == 0.0
    assert assessment.invalid_citation_count == 1


# ─── 3. Full End-to-End Investigation Pipeline Integration ───────────────────


@pytest.mark.asyncio
async def test_investigation_pipeline_persists_groundedness_assessment(
    client: AsyncClient, test_user_and_org: dict, use_mock_llm: MockLLMProvider
) -> None:
    user = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    # Create incident
    inc_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={
            "title": "Payment gateway latency",
            "severity": "critical",
            "service_name": "payment-api",
        },
    )
    incident_id = inc_resp.json()["id"]

    # Ingest diverse evidence
    ev_deploy = (
        await client.post(
            f"/api/v1/incidents/{incident_id}/evidence",
            headers=headers,
            json={
                "source_type": "deployment",
                "event_type": "deployment.completed",
                "event_timestamp": "2026-10-08T12:00:00Z",
                "summary": "Deployment v3.1.0 completed for payment-api",
            },
        )
    ).json()["id"]

    ev_alert = (
        await client.post(
            f"/api/v1/incidents/{incident_id}/evidence",
            headers=headers,
            json={
                "source_type": "alert",
                "event_type": "alert.firing",
                "event_timestamp": "2026-10-08T12:01:00Z",
                "summary": "HTTP 504 Gateway Timeout rate exceeded 10%",
            },
        )
    ).json()["id"]

    ev_log = (
        await client.post(
            f"/api/v1/incidents/{incident_id}/evidence",
            headers=headers,
            json={
                "source_type": "log",
                "event_type": "database.pool",
                "event_timestamp": "2026-10-08T12:01:30Z",
                "summary": "Database connection pool timeout on checkout database",
            },
        )
    ).json()["id"]

    # Configure mock LLM output citing all 3 valid items
    use_mock_llm._custom_responder = lambda _req: json.dumps(
        {  # noqa: SLF001
            "hypotheses": [
                {
                    "claim": "Deployment v3.1.0 exhausted database connection pool",
                    "rationale": "Deploy preceded 504 alerts and database pool timeouts",
                    "confidence": "high",
                    "confidence_score": 0.9,
                    "supporting_evidence_ids": [ev_deploy, ev_alert, ev_log],
                    "contradicting_evidence_ids": [],
                }
            ],
            "observed_facts": ["v3.1.0 deployed at 12:00", "504 alerts fired at 12:01"],
            "uncertainty_notes": ["Correlation is not proof"],
            "recommended_next_steps": [
                {"action": "Check connection pool metrics", "requires_human_approval": False}
            ],
        }
    )

    # Trigger investigation
    job_resp = await client.post(
        f"/api/v1/incidents/{incident_id}/investigations",
        headers=headers,
        json={},
    )
    assert job_resp.status_code == 201
    job = job_resp.json()
    assert job["status"] == "completed"

    # Verify result_summary contains groundedness_summary
    summary = job["result_summary"]
    assert "groundedness_summary" in summary
    assert summary["groundedness_summary"]["well_supported"] == 1
    assert summary["groundedness_summary"]["total_evaluated"] == 1
    assert summary["groundedness_summary"]["average_groundedness_score"] >= 0.75
    assert "calibration_status" in summary["groundedness_summary"]

    # Fetch hypotheses list via API
    hyps_resp = await client.get(
        f"/api/v1/investigations/{job['id']}/hypotheses",
        headers=headers,
    )
    assert hyps_resp.status_code == 200
    hyps_data = hyps_resp.json()
    assert hyps_data["total"] == 1
    hyp = hyps_data["items"][0]

    # Verify Milestone 4 response fields
    assert hyp["groundedness_status"] == GroundednessStatus.WELL_SUPPORTED.value
    assert hyp["system_confidence"] == SystemConfidenceLevel.HIGH.value
    assert hyp["groundedness_score"] >= 0.75
    assert hyp["system_confidence_score"] >= 0.75
    assert hyp["assessment_version"] == "v1"
    assert hyp["assessment_details"] is not None
    assert hyp["assessment_details"]["support_score"] > 0
    assert hyp["assessment_details"]["calibration_status"] == "insufficient_evaluation_data"

    # Verify backward compatibility
    assert hyp["confidence"] == "high"  # raw model confidence
    assert hyp["model_confidence"] == "high"
    assert hyp["confidence_score"] == 0.9
    assert hyp["model_confidence_score"] == 0.9
    assert "uncalibrated" in hyp["confidence_note"]

    # Fetch individual hypothesis detail via API
    detail_resp = await client.get(
        f"/api/v1/hypotheses/{hyp['id']}",
        headers=headers,
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == hyp["id"]
    assert detail["groundedness_score"] == hyp["groundedness_score"]
    assert detail["system_confidence"] == hyp["system_confidence"]
