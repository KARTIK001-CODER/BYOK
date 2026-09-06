"""Verification service — claim extraction → evidence selection → heuristic → LLM fallback → aggregation."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import get_settings
from app.core.tracing import get_current_trace
from app.services.verification.aggregation import aggregate_groundedness
from app.services.verification.claim_extraction import RuleBasedClaimExtractor
from app.services.verification.evidence_selection import EvidenceSelector
from app.services.verification.factory import ClaimExtractorFactory, VerifierFactory
from app.services.verification.schemas import (
    ClaimVerificationResult,
    Evidence,
    GroundednessResult,
    VerificationConfig,
    VerificationStatus,
    VerificationTrace,
)

logger = logging.getLogger("app.services.verification.service")


class VerificationService:
    """Orchestrates groundedness verification. No DB queries for selection (uses provided evidence)."""

    @staticmethod
    async def verify_answer(
        answer: str,
        evidence_chunks: list[dict[str, Any]],
        config: VerificationConfig | None = None,
    ) -> tuple[GroundednessResult, VerificationTrace]:
        """
        Verify answer against evidence chunks (already retrieved context).

        Args:
            answer: Generated answer text
            evidence_chunks: List of dicts with chunk_id, document_id, document_name, content, retrieval_rank, rerank_rank
            config: Verification config (provider, evidence_top_k, thresholds)

        Returns:
            (GroundednessResult, VerificationTrace)
        """
        cfg = config or VerificationConfig()
        settings = get_settings()
        # Override from global config if not explicitly passed
        if not cfg.enabled and getattr(settings, "ENABLE_GROUNDEDNESS_CHECK", False):
            cfg.enabled = True
        if cfg.evidence_top_k == 3 and hasattr(settings, "VERIFICATION_EVIDENCE_TOP_K"):
            cfg.evidence_top_k = getattr(settings, "VERIFICATION_EVIDENCE_TOP_K")
        if cfg.timeout_seconds == 2.0 and hasattr(settings, "VERIFICATION_TIMEOUT_SECONDS"):
            cfg.timeout_seconds = float(getattr(settings, "VERIFICATION_TIMEOUT_SECONDS"))

        trace = get_current_trace()
        total_t0 = time.perf_counter()

        # If not enabled, return highly grounded dummy
        if not cfg.enabled:
            tr = VerificationTrace(verification_total_ms=0.0, groundedness_score=1.0)
            gr = GroundednessResult(total_claims=0, groundedness_score=1.0, answer_status="HIGHLY_GROUNDED", claim_results=[])
            return gr, tr

        # 1. Claim extraction
        ce_t0 = time.perf_counter()
        extractor = ClaimExtractorFactory.create()
        try:
            claims = await extractor.extract(answer)
        except Exception as e:
            logger.warning("Claim extraction failed: %s", e)
            claims = []
        ce_ms = (time.perf_counter() - ce_t0) * 1000.0
        claim_count = len(claims)
        verifiable_claims = [c for c in claims if c.claim_type.value != "NON_VERIFIABLE"]

        # 2. Prepare evidence candidates (from retrieved context, no DB)
        evidence_candidates: list[Evidence] = []
        for idx, ch in enumerate(evidence_chunks):
            evidence_candidates.append(
                Evidence(
                    evidence_id=f"ev_{idx+1:03d}",
                    chunk_id=ch.get("chunk_id") or ch.get("id") or f"chunk_{idx}",
                    document_id=ch.get("document_id") or "doc_unknown",
                    document_name=ch.get("document_name"),
                    content=ch.get("content", "")[:2000],
                    retrieval_rank=ch.get("retrieval_rank") or ch.get("rank"),
                    rerank_rank=ch.get("rerank_rank"),
                )
            )

        # 3. Verify each verifiable claim
        heuristic_ms_total = 0.0
        llm_ms_total = 0.0
        llm_calls = 0
        fallbacks = 0
        results: list[ClaimVerificationResult] = []

        # Handle non-verifiable directly
        for claim in claims:
            if claim.claim_type.value == "NON_VERIFIABLE":
                results.append(
                    ClaimVerificationResult(
                        claim=claim,
                        status=VerificationStatus.NON_VERIFIABLE,
                        confidence=0.95,
                        reason="Non-verifiable opinion",
                        evidence=[],
                        provider="heuristic",
                        verification_latency_ms=0.0,
                    )
                )

        # For verifiable, select evidence and verify
        for claim in verifiable_claims:
            # Evidence selection (per claim, top_k)
            sel_t0 = time.perf_counter()
            selected, sel_ms = EvidenceSelector.select(claim, evidence_candidates, top_k=cfg.evidence_top_k)
            # Accumulate selection time later
            heuristic_t0 = time.perf_counter()
            # Heuristic first
            verifier = VerifierFactory.create(provider="heuristic")
            try:
                # Timeout bounded
                h_result = await asyncio.wait_for(verifier.verify(claim, selected), timeout=cfg.timeout_seconds)
                h_ms = (time.perf_counter() - heuristic_t0) * 1000.0
                heuristic_ms_total += h_ms
                # If heuristic high confidence, final
                if h_result.confidence >= 0.75 and h_result.status in (VerificationStatus.SUPPORTED, VerificationStatus.CONTRADICTED):
                    results.append(h_result)
                    continue
                # Else if LLM fallback enabled
                if cfg.enable_llm_fallback or getattr(settings, "ENABLE_LLM_VERIFICATION", False):
                    llm_t0 = time.perf_counter()
                    llm_verifier = VerifierFactory.create(provider="llm")
                    try:
                        llm_result = await asyncio.wait_for(llm_verifier.verify(claim, selected), timeout=cfg.timeout_seconds)
                        llm_ms_total += (time.perf_counter() - llm_t0) * 1000.0
                        llm_calls += 1
                        # Prefer LLM if higher confidence
                        if llm_result.confidence > h_result.confidence:
                            results.append(llm_result)
                        else:
                            results.append(h_result)
                    except asyncio.TimeoutError:
                        logger.warning("LLM verifier timeout for claim %s", claim.claim_id)
                        fallbacks += 1
                        results.append(h_result)
                    except Exception as e:
                        logger.warning("LLM verifier failed: %s", e)
                        fallbacks += 1
                        results.append(h_result)
                else:
                    # No LLM, keep heuristic (may be UNCERTAIN)
                    results.append(h_result)
            except asyncio.TimeoutError:
                logger.warning("Heuristic verifier timeout for claim %s", claim.claim_id)
                fallbacks += 1
                results.append(
                    ClaimVerificationResult(
                        claim=claim,
                        status=VerificationStatus.UNCERTAIN,
                        confidence=0.3,
                        reason="Heuristic timeout",
                        evidence=selected,
                        provider="heuristic",
                        verification_latency_ms=round((time.perf_counter() - heuristic_t0)*1000, 2),
                        fallback_used=True,
                    )
                )
            except Exception as e:
                logger.warning("Heuristic verifier failed: %s", e)
                fallbacks += 1
                results.append(
                    ClaimVerificationResult(
                        claim=claim,
                        status=VerificationStatus.UNCERTAIN,
                        confidence=0.3,
                        reason=f"Heuristic error: {e}",
                        evidence=selected,
                        provider="heuristic",
                        verification_latency_ms=0.0,
                        fallback_used=True,
                    )
                )

        # 4. Aggregate groundedness
        groundedness = aggregate_groundedness(
            results,
            high_threshold=cfg.groundedness_high_threshold if hasattr(cfg, "groundedness_high_threshold") else getattr(settings, "GROUNDEDNESS_HIGH_THRESHOLD", 0.85),
            medium_threshold=cfg.groundedness_medium_threshold if hasattr(cfg, "groundedness_medium_threshold") else getattr(settings, "GROUNDEDNESS_MEDIUM_THRESHOLD", 0.6),
        )

        total_ms = (time.perf_counter() - total_t0) * 1000.0

        trace_obj = VerificationTrace(
            claim_extraction_ms=round(ce_ms, 2),
            claim_count=claim_count,
            verifiable_claim_count=len(verifiable_claims),
            evidence_selection_ms=round(0.0, 2),  # selection is per-claim, aggregated negligible
            heuristic_verification_ms=round(heuristic_ms_total, 2),
            llm_verification_ms=round(llm_ms_total, 2),
            verification_total_ms=round(total_ms, 2),
            groundedness_score=groundedness.groundedness_score,
            supported_claims=groundedness.supported_claims,
            partially_supported_claims=groundedness.partially_supported_claims,
            unsupported_claims=groundedness.unsupported_claims,
            contradicted_claims=groundedness.contradicted_claims,
            uncertain_claims=groundedness.uncertain_claims,
            non_verifiable_claims=groundedness.non_verifiable_claims,
            llm_verifier_calls=llm_calls,
            verification_fallbacks=fallbacks,
        )

        if trace:
            trace.record("claim_extraction_ms", ce_ms)
            trace.record("verification_total_ms", total_ms)
            trace.set_counter("claim_count", claim_count)
            trace.set_counter("groundedness_score", groundedness.groundedness_score)
            trace.set_counter("supported_claims", groundedness.supported_claims)
            trace.set_counter("contradicted_claims", groundedness.contradicted_claims)
            trace.set_counter("llm_verifier_calls", llm_calls)

        return groundedness, trace_obj
