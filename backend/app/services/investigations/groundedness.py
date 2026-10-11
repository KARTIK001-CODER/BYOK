"""TracePilot Groundedness, Evidence Quality & Confidence Calibration Engine (Milestone 4).

Evaluates whether AI-generated root-cause hypotheses are genuinely supported by
persisted evidence, exposing contradictions, unsupported assertions, temporal
inconsistencies, and duplicate evidence inflation.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. LLM confidence is an untrusted self-assessment; system confidence is derived
   deterministically from empirical evidence quality.
2. System confidence is an evidence-quality score, NOT a statistically calibrated
   probability.
3. Temporal consistency represents evidence compatibility, never proof of causality.
4. Contradictory evidence is never hidden or suppressed.
5. Invalid evidence citations receive zero grounding credit and cannot rescue hypotheses.
6. Tenant and incident isolation are strictly enforced on all evidence lookups.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.evidence import EvidenceEvent, EvidenceSourceType
from app.models.investigation import (
    GroundednessStatus,
    HypothesisStatus,
    InvestigationJob,
    RootCauseHypothesis,
    SystemConfidenceLevel,
)

logger = logging.getLogger("app.services.investigations.groundedness")

_MECHANISM_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    (
        "database_connection_pool",
        ("connection leak", "pool exhaustion", "connection pool", "database pool", "pool timeout"),
        ("pool", "connection", "database", "timeout", "db", "postgres", "sql", "rds"),
    ),
    (
        "memory_leak_oom",
        ("memory leak", "out of memory", "oom", "oomkiller", "heap exhaustion"),
        ("memory", "oom", "heap", "ram", "kill"),
    ),
    (
        "cpu_saturation",
        ("cpu throttle", "cpu spike", "high cpu", "cpu saturation"),
        ("cpu", "throttle", "load"),
    ),
    (
        "disk_exhaustion",
        ("disk full", "disk exhaustion", "no space left", "disk space"),
        ("disk", "space", "storage", "filesystem"),
    ),
    (
        "network_partition",
        ("network partition", "packet loss", "dns failure", "connection refused"),
        ("network", "packet", "dns", "refused", "connect"),
    ),
]


@dataclass
class GroundednessAssessment:
    """Internal and persisted assessment representing hypothesis evidence quality."""

    hypothesis_id: str
    groundedness_score: float
    system_confidence_score: float
    system_confidence: str
    groundedness_status: str
    support_score: float
    contradiction_score: float
    citation_score: float
    temporal_score: float
    coverage_score: float
    diversity_score: float
    retrieval_score: float
    unsupported_claim_score: float
    assessment_status: str
    assessment_reasons: list[str]
    confidence_note: str
    assessment_version: str = "v1"
    calibration_status: str = "insufficient_evaluation_data"
    valid_supporting_count: int = 0
    valid_contradicting_count: int = 0
    invalid_citation_count: int = 0
    distinct_source_types: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


class GroundednessEvaluator:
    """Deterministic, explainable evaluator for root-cause hypotheses."""

    @classmethod
    def evaluate(
        cls,
        hypothesis_id: str,
        claim: str,
        rationale: str,
        raw_status: str,
        links: list[dict[str, Any]],
        evidence_map: dict[str, EvidenceEvent],
        retrieval_metadata_map: dict[str, dict[str, Any]] | None = None,
        version: str = "v1",
    ) -> GroundednessAssessment:
        retrieval_map = retrieval_metadata_map or {}
        cal_status = "insufficient_evaluation_data"

        # 1. Citation validity & boundary checks
        valid_supporting_events: list[EvidenceEvent] = []
        valid_contradicting_events: list[EvidenceEvent] = []
        invalid_citations: list[str] = []

        for link in links:
            eid = link.get("evidence_event_id") or link.get("id")
            link_type = link.get("link_type", "supports")
            if eid in evidence_map:
                ev = evidence_map[eid]
                if link_type == "contradicts":
                    valid_contradicting_events.append(ev)
                else:
                    valid_supporting_events.append(ev)
            else:
                if eid:
                    invalid_citations.append(eid)

        num_sup = len(valid_supporting_events)
        num_contra = len(valid_contradicting_events)
        num_invalid = len(invalid_citations)

        # Reject immediately if no valid evidence or explicitly rejected
        if raw_status == HypothesisStatus.REJECTED.value or num_sup == 0:
            reasons = [
                "Hypothesis cited zero valid supporting evidence events for this incident.",
            ]
            if num_invalid > 0:
                reasons.append(
                    f"Cited {num_invalid} reference(s) that could not be resolved to valid incident evidence."
                )
            reasons.append("Invalid or ungrounded citations receive zero grounding credit.")
            return GroundednessAssessment(
                hypothesis_id=hypothesis_id,
                groundedness_score=0.0,
                system_confidence_score=0.0,
                system_confidence=SystemConfidenceLevel.LOW.value,
                groundedness_status=GroundednessStatus.REJECTED.value,
                support_score=0.0,
                contradiction_score=1.0 if num_contra > 0 else 0.0,
                citation_score=0.0,
                temporal_score=0.0,
                coverage_score=0.0,
                diversity_score=0.0,
                retrieval_score=0.0,
                unsupported_claim_score=1.0,
                assessment_status=GroundednessStatus.REJECTED.value,
                assessment_reasons=reasons,
                confidence_note=(
                    "Model-reported confidence is an uncalibrated self-assessment, "
                    "not a statistically calibrated probability. "
                    "System confidence is zero due to absent or invalid evidence citations."
                ),
                assessment_version=version,
                calibration_status=cal_status,
                valid_supporting_count=0,
                valid_contradicting_count=num_contra,
                invalid_citation_count=num_invalid,
                distinct_source_types=[],
                details={"rejection_reason": "No valid supporting citations found."},
            )

        citation_score = num_sup / (num_sup + num_invalid) if (num_sup + num_invalid) > 0 else 0.0

        # 2. Evidence diversity & duplicate damping
        source_types = [e.source_type for e in valid_supporting_events]
        distinct_sources = sorted(set(source_types))
        unique_summaries = {e.summary.strip().lower() for e in valid_supporting_events}
        duplicate_count = num_sup - len(unique_summaries)

        # Dampen effective count when many duplicate logs/events are cited
        effective_count = len(unique_summaries) + (duplicate_count * 0.1)

        if len(distinct_sources) >= 3:
            diversity_score = 1.00
        elif len(distinct_sources) == 2:
            diversity_score = 0.80
        else:
            diversity_score = 0.25 if duplicate_count > 0 else 0.50

        # 3. Evidence coverage
        if effective_count >= 3 and len(distinct_sources) >= 2:
            coverage_score = 1.00
        elif effective_count >= 2 and len(distinct_sources) >= 2:
            coverage_score = 0.70
        elif effective_count >= 2:
            coverage_score = 0.45
        elif effective_count >= 1:
            coverage_score = 0.25 if duplicate_count > 0 else 0.40
        else:
            coverage_score = 0.10

        # 4. Temporal consistency
        trigger_types = {
            EvidenceSourceType.DEPLOYMENT.value,
            EvidenceSourceType.GIT.value,
            EvidenceSourceType.MANUAL.value,
        }
        symptom_types = {
            EvidenceSourceType.ALERT.value,
            EvidenceSourceType.METRIC.value,
            EvidenceSourceType.LOG.value,
            EvidenceSourceType.TRACE.value,
        }

        trigger_events = [
            e
            for e in valid_supporting_events
            if e.source_type in trigger_types or "deploy" in e.event_type.lower()
        ]
        symptom_events = [
            e
            for e in valid_supporting_events
            if e.source_type in symptom_types
            or "alert" in e.event_type.lower()
            or "502" in e.summary.lower()
            or "timeout" in e.summary.lower()
        ]

        reasons: list[str] = []
        if trigger_events and symptom_events:
            earliest_trigger = min(e.event_timestamp for e in trigger_events)
            earliest_symptom = min(e.event_timestamp for e in symptom_events)
            if earliest_trigger <= earliest_symptom:
                temporal_score = 1.00
                reasons.append(
                    "Temporal sequence is compatible: alleged trigger preceded observed symptoms."
                )
            else:
                temporal_score = 0.10
                reasons.append(
                    "Temporal inconsistency: alleged trigger occurred after initial symptoms were observed."
                )
        elif duplicate_count > 0 and len(distinct_sources) == 1:
            temporal_score = 0.50
            reasons.append("Single-source duplicated events cannot establish temporal progression.")
        else:
            temporal_score = 0.80
            reasons.append("Temporal order is chronologically compatible with recorded evidence.")

        # 5. Contradicting evidence
        if num_contra == 0:
            contradiction_score = 0.0
            reasons.append("No contradicting evidence cited.")
        else:
            contra_ratio = num_contra / (num_sup + num_contra)
            contradiction_score = min(1.0, round(contra_ratio * 1.5, 2))
            reasons.append(
                f"{num_contra} contradicting evidence event(s) cited against this hypothesis."
            )

        # 6. Unsupported claim / assertion detection
        text_corpus = f"{claim} {rationale}".lower()
        supporting_evidence_text = " ".join(
            f"{e.summary} {e.event_type} {e.source_type}".lower() for e in valid_supporting_events
        )

        unsupported_claims: list[str] = []
        for mech_name, triggers, corroborating_terms in _MECHANISM_RULES:
            if any(t in text_corpus for t in triggers):
                # Mechanism is claimed; does cited evidence substantiate it?
                has_corroboration = any(
                    term in supporting_evidence_text for term in corroborating_terms
                )
                if not has_corroboration:
                    unsupported_claims.append(mech_name)

        if unsupported_claims:
            unsupported_claim_score = 0.50
            reasons.append(
                f"Asserts failure mechanism ({', '.join(unsupported_claims)}) without corroborating evidence in cited telemetry."
            )
        else:
            unsupported_claim_score = 0.0

        # 7. Retrieval quality signal
        retrieval_scores: list[float] = []
        for e in valid_supporting_events:
            r_meta = retrieval_map.get(e.id)
            if r_meta and "score" in r_meta and r_meta["score"] is not None:
                retrieval_scores.append(float(r_meta["score"]))
        if retrieval_scores:
            retrieval_score = round(sum(retrieval_scores) / len(retrieval_scores), 2)
            retrieval_score = max(0.0, min(1.0, retrieval_score))
        else:
            retrieval_score = 0.75

        # 8. Score Synthesis
        support_score = round(
            0.40 * coverage_score + 0.35 * diversity_score + 0.25 * retrieval_score, 2
        )

        base_groundedness = (
            0.35 * coverage_score
            + 0.25 * temporal_score
            + 0.25 * diversity_score
            + 0.15 * retrieval_score
        ) * citation_score

        raw_groundedness = base_groundedness * (1.0 - 0.70 * contradiction_score) - (
            0.25 * unsupported_claim_score
        )
        groundedness_score = max(0.0, min(1.0, round(raw_groundedness, 2)))

        # Status assignment
        if contradiction_score >= 0.40:
            status = GroundednessStatus.CONTESTED.value
        elif groundedness_score >= 0.75:
            status = GroundednessStatus.WELL_SUPPORTED.value
        elif groundedness_score >= 0.45:
            status = GroundednessStatus.PARTIALLY_SUPPORTED.value
        else:
            status = GroundednessStatus.WEAKLY_SUPPORTED.value

        # System Confidence Calculation (Strictly monotonic)
        raw_system_conf = groundedness_score * (1.0 - 0.80 * contradiction_score)
        system_confidence_score = max(0.0, min(1.0, round(raw_system_conf, 2)))

        if (
            status
            in (
                GroundednessStatus.REJECTED.value,
                GroundednessStatus.CONTESTED.value,
                GroundednessStatus.WEAKLY_SUPPORTED.value,
            )
            or system_confidence_score < 0.40
        ):
            system_confidence_level = SystemConfidenceLevel.LOW.value
        elif system_confidence_score < 0.75:
            system_confidence_level = SystemConfidenceLevel.MEDIUM.value
        else:
            system_confidence_level = SystemConfidenceLevel.HIGH.value

        # Evidence summary reason
        source_breakdown = ", ".join(distinct_sources)
        reasons.insert(
            0,
            f"{num_sup} valid supporting evidence events cited across {len(distinct_sources)} distinct source type(s) ({source_breakdown}).",
        )
        if duplicate_count > 0:
            reasons.append(
                f"Contains {duplicate_count} duplicated or near-identical evidence event(s); confidence inflation was dampened."
            )
        reasons.append(
            "Temporal correlation alone does not establish causation; sequence is not causal proof."
        )

        confidence_note = (
            "Model-reported confidence is an uncalibrated self-assessment, "
            "not a statistically calibrated probability. "
            "System confidence is an evidence-quality score, not a calibrated probability."
        )

        return GroundednessAssessment(
            hypothesis_id=hypothesis_id,
            groundedness_score=groundedness_score,
            system_confidence_score=system_confidence_score,
            system_confidence=system_confidence_level,
            groundedness_status=status,
            support_score=support_score,
            contradiction_score=contradiction_score,
            citation_score=round(citation_score, 2),
            temporal_score=temporal_score,
            coverage_score=coverage_score,
            diversity_score=diversity_score,
            retrieval_score=retrieval_score,
            unsupported_claim_score=unsupported_claim_score,
            assessment_status=status,
            assessment_reasons=reasons,
            confidence_note=confidence_note,
            assessment_version=version,
            calibration_status=cal_status,
            valid_supporting_count=num_sup,
            valid_contradicting_count=num_contra,
            invalid_citation_count=num_invalid,
            distinct_source_types=distinct_sources,
            details={
                "effective_evidence_count": effective_count,
                "duplicate_count": duplicate_count,
                "unsupported_mechanisms": unsupported_claims,
            },
        )


class GroundednessService:
    """High-level orchestration service for evaluating and persisting groundedness assessments."""

    @classmethod
    async def evaluate_and_persist_job_hypotheses(
        cls,
        session: AsyncSession,
        job: InvestigationJob,
        retrieved: list[Any] | None = None,
    ) -> list[GroundednessAssessment]:
        """Evaluate and persist groundedness for all hypotheses belonging to an investigation job.

        PERFORMANCE GUARANTEE: Loads all referenced evidence events in a single
        tenant-scoped, incident-scoped query to guarantee zero N+1 queries.
        """
        start_time = time.monotonic()
        settings = get_settings()
        version = settings.GROUNDING_VERSION

        # 1. Load hypotheses and their links
        stmt = (
            select(RootCauseHypothesis)
            .where(
                RootCauseHypothesis.investigation_job_id == job.id,
                RootCauseHypothesis.organization_id == job.organization_id,
            )
            .options(selectinload(RootCauseHypothesis.evidence_links))
            .order_by(RootCauseHypothesis.created_at.asc(), RootCauseHypothesis.id.asc())
        )
        hypotheses = (await session.execute(stmt)).scalars().all()
        if not hypotheses:
            return []

        # 2. Collect all cited evidence IDs
        cited_evidence_ids = {
            link.evidence_event_id for hyp in hypotheses for link in hyp.evidence_links
        }

        # 3. Batch load all referenced evidence events for this incident and organization
        evidence_map: dict[str, EvidenceEvent] = {}
        if cited_evidence_ids:
            ev_stmt = select(EvidenceEvent).where(
                EvidenceEvent.id.in_(cited_evidence_ids),
                EvidenceEvent.organization_id == job.organization_id,
                EvidenceEvent.incident_id == job.incident_id,
            )
            events = (await session.execute(ev_stmt)).scalars().all()
            evidence_map = {e.id: e for e in events}

        # 4. Map retrieval metadata
        retrieval_metadata_map: dict[str, dict[str, Any]] = {}
        if retrieved:
            for item in retrieved:
                ev_obj = getattr(item, "event", item)
                eid = getattr(ev_obj, "id", None)
                if eid:
                    retrieval_metadata_map[eid] = {
                        "score": getattr(item, "score", None),
                        "rank": getattr(item, "rank", None),
                        "retrieval_method": getattr(item, "retrieval_method", "hybrid"),
                    }

        # 5. Evaluate and update each hypothesis
        assessments: list[GroundednessAssessment] = []
        for hyp in hypotheses:
            try:
                links_data = [
                    {
                        "evidence_event_id": link.evidence_event_id,
                        "link_type": link.link_type,
                        "excerpt": link.excerpt,
                    }
                    for link in hyp.evidence_links
                ]
                assessment = GroundednessEvaluator.evaluate(
                    hypothesis_id=hyp.id,
                    claim=hyp.claim,
                    rationale=hyp.rationale,
                    raw_status=hyp.status,
                    links=links_data,
                    evidence_map=evidence_map,
                    retrieval_metadata_map=retrieval_metadata_map,
                    version=version,
                )

                # Persist directly on RootCauseHypothesis
                hyp.groundedness_score = assessment.groundedness_score
                hyp.system_confidence_score = assessment.system_confidence_score
                hyp.system_confidence = assessment.system_confidence
                hyp.groundedness_status = assessment.groundedness_status
                hyp.assessment_version = assessment.assessment_version
                hyp.assessment_details = assessment.to_dict()

                # Align hypothesis lifecycle status
                if assessment.groundedness_status == GroundednessStatus.REJECTED.value:
                    hyp.status = HypothesisStatus.REJECTED.value
                elif assessment.groundedness_status == GroundednessStatus.CONTESTED.value:
                    hyp.status = HypothesisStatus.CONTESTED.value
                elif hyp.status != HypothesisStatus.REJECTED.value:
                    hyp.status = HypothesisStatus.SUPPORTED.value

                assessments.append(assessment)

            except Exception:
                # SAFE ERROR CONTAINMENT: Never fail the investigation if evaluation encounters an error
                logger.exception("Groundedness evaluation failed for hypothesis %s", hyp.id)
                fallback_assessment = GroundednessAssessment(
                    hypothesis_id=hyp.id,
                    groundedness_score=0.0,
                    system_confidence_score=0.0,
                    system_confidence=SystemConfidenceLevel.UNKNOWN.value,
                    groundedness_status=GroundednessStatus.EVALUATION_FAILED.value,
                    support_score=0.0,
                    contradiction_score=0.0,
                    citation_score=0.0,
                    temporal_score=0.0,
                    coverage_score=0.0,
                    diversity_score=0.0,
                    retrieval_score=0.0,
                    unsupported_claim_score=0.0,
                    assessment_status=GroundednessStatus.EVALUATION_FAILED.value,
                    assessment_reasons=[
                        "Groundedness evaluation failed unexpectedly; score unavailable."
                    ],
                    confidence_note="Evaluation failed safely; system confidence is unknown.",
                    assessment_version=version,
                    calibration_status="insufficient_evaluation_data",
                )
                hyp.groundedness_score = None
                hyp.system_confidence_score = None
                hyp.system_confidence = SystemConfidenceLevel.UNKNOWN.value
                hyp.groundedness_status = GroundednessStatus.EVALUATION_FAILED.value
                hyp.assessment_version = version
                hyp.assessment_details = fallback_assessment.to_dict()
                assessments.append(fallback_assessment)

        await session.commit()
        for hyp in hypotheses:
            await session.refresh(hyp)

        duration = time.monotonic() - start_time
        logger.info(
            "Completed groundedness evaluation for job %s: %d hypotheses evaluated in %.3fs",
            job.id,
            len(assessments),
            duration,
        )
        return assessments
