"""Evaluation runner — loads dataset, runs retrievers via adapters, collects results."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.evaluation.dataset import EvaluationDatasetLoader
from app.services.evaluation.metrics import EvaluationMetrics
from app.services.evaluation.schemas import (
    CaseResult,
    EvaluationCategory,
    EvaluationConfigSnapshot,
    EvaluationDataset,
    EvaluationReport,
    MetricResult,
    RetrievedResult,
)
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService

logger = logging.getLogger("app.services.evaluation.runner")


class RetrieverAdapter(Protocol):
    """Protocol for retriever adapters — allows future HyDE, reranker, router without inheritance."""

    name: str

    async def retrieve(
        self,
        session: AsyncSession,
        organization_id: str,
        query: str,
        top_k: int,
        candidate_k: int = 50,
    ) -> list[RetrievedResult]:
        ...


@dataclass
class VectorAdapter:
    name: str = "vector"

    async def retrieve(self, session: AsyncSession, organization_id: str, query: str, top_k: int, candidate_k: int = 50) -> list[RetrievedResult]:
        req = RetrievalRequest(query=query, top_k=top_k, candidate_k=candidate_k, search_mode=SearchMode.VECTOR)
        resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
        return [
            RetrievedResult(
                rank=r.rank,
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_name=r.document_name,
                score=r.score,
                is_relevant=False,  # filled by runner
            )
            for r in resp.results
        ]


@dataclass
class KeywordAdapter:
    name: str = "keyword"

    async def retrieve(self, session: AsyncSession, organization_id: str, query: str, top_k: int, candidate_k: int = 50) -> list[RetrievedResult]:
        req = RetrievalRequest(query=query, top_k=top_k, candidate_k=candidate_k, search_mode=SearchMode.KEYWORD)
        resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
        return [
            RetrievedResult(
                rank=r.rank,
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_name=r.document_name,
                score=r.score,
                is_relevant=False,
            )
            for r in resp.results
        ]


@dataclass
class HybridAdapter:
    name: str = "hybrid"

    async def retrieve(self, session: AsyncSession, organization_id: str, query: str, top_k: int, candidate_k: int = 50) -> list[RetrievedResult]:
        req = RetrievalRequest(query=query, top_k=top_k, candidate_k=candidate_k, search_mode=SearchMode.HYBRID)
        resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
        # Preserve fusion debug info if available (rrf)
        return [
            RetrievedResult(
                rank=r.rank,
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_name=r.document_name,
                score=r.score,
                rrf_score=r.rrf_score,
                is_relevant=False,
            )
            for r in resp.results
        ]


@dataclass
class AdaptiveAdapter:
    """Phase 2.1 — routes via Query Intelligence (deterministic, no LLM/DB)."""

    name: str = "adaptive"

    async def retrieve(
        self, session: AsyncSession, organization_id: str, query: str, top_k: int, candidate_k: int = 50
    ) -> list[RetrievedResult]:
        # Force adaptive path even if global flag false — directly analyze and dispatch
        from app.services.query_intelligence.analyzer import QueryAnalyzer
        from app.core.config import get_settings

        settings = get_settings()
        analysis = QueryAnalyzer.analyze(query)
        strat = analysis.strategy.strategy.value  # VECTOR / KEYWORD / HYBRID / HYBRID_WIDE

        # Map to search mode + candidate_k
        if strat == "KEYWORD":
            req = RetrievalRequest(query=query, top_k=top_k, candidate_k=candidate_k, search_mode=SearchMode.KEYWORD)
        elif strat == "VECTOR":
            req = RetrievalRequest(query=query, top_k=top_k, candidate_k=candidate_k, search_mode=SearchMode.VECTOR)
        elif strat == "HYBRID_WIDE":
            ck = getattr(settings, "HYBRID_WIDE_CANDIDATE_K", 50)
            req = RetrievalRequest(query=query, top_k=top_k, candidate_k=ck, search_mode=SearchMode.HYBRID)
        else:
            req = RetrievalRequest(query=query, top_k=top_k, candidate_k=candidate_k, search_mode=SearchMode.HYBRID)

        # Temporarily enable flag so RetrievalService also records qi timings if needed, but we already analyzed
        # To avoid double analysis, pass provider None; RetrievalService will re-analyze if flag true.
        # Instead, disable flag for this inner call and use our already chosen req
        original_flag = settings.ENABLE_QUERY_INTELLIGENCE
        try:
            # Disable inner adaptive to prevent double routing
            settings.ENABLE_QUERY_INTELLIGENCE = False
            resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
        finally:
            settings.ENABLE_QUERY_INTELLIGENCE = original_flag

        # Attach analysis to trace for reporting (store in adapter for later aggregation)
        # We return retrieved + analysis via side channel using a thread-local is not needed; evaluation runner will record separately
        # For now, stash analysis on retrieved objects via score field is not needed — we just return results
        # The runner can re-analyze to get strategy distribution; we will handle there
        return [
            RetrievedResult(
                rank=r.rank,
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_name=r.document_name,
                score=r.score,
                vector_rank=None,
                keyword_rank=None,
                rrf_score=r.rrf_score,
                is_relevant=False,
            )
            for r in resp.results
        ]


ADAPTER_REGISTRY: dict[str, RetrieverAdapter] = {
    "vector": VectorAdapter(),
    "keyword": KeywordAdapter(),
    "hybrid": HybridAdapter(),
    "adaptive": AdaptiveAdapter(),
}


def get_adapter(name: str) -> RetrieverAdapter:
    key = name.strip().lower()
    if key not in ADAPTER_REGISTRY:
        raise ValueError(f"Unknown retriever adapter '{name}'. Available: {list(ADAPTER_REGISTRY.keys())}")
    return ADAPTER_REGISTRY[key]  # type: ignore[return-value]


class EvaluationRunner:
    """Load dataset, run retriever, calculate metrics, generate report."""

    def __init__(
        self,
        dataset_path: Path | str,
        retriever: str = "hybrid",
        top_k: int = 5,
        top_k_values: list[int] | None = None,
        candidate_k: int | None = None,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.retriever_name = retriever
        self.top_k = top_k
        self.top_k_values = top_k_values or [1, 3, 5, 10]
        settings = get_settings()
        self.candidate_k = candidate_k or max(top_k * 4, 30)
        self.settings = settings

    async def run(
        self,
        session: AsyncSession,
        organization_id: str,
        dataset: EvaluationDataset | None = None,
        adapter: RetrieverAdapter | None = None,
    ) -> EvaluationReport:
        ds = dataset or EvaluationDatasetLoader.load(self.dataset_path)
        adapter = adapter or get_adapter(self.retriever_name)
        top_k = self.top_k
        top_k_values = self.top_k_values

        # Resolve stable document_name -> chunk_id mapping for relevance
        # We match expected.document_name against retrieved.document_name or chunk content snippet
        case_results: list[CaseResult] = []
        failures: list[CaseResult] = []
        start_all = time.perf_counter()

        for case in ds.cases:
            t0 = time.perf_counter()
            # Run retrieval
            try:
                retrieved = await adapter.retrieve(
                    session=session,
                    organization_id=organization_id,
                    query=case.query,
                    top_k=top_k,
                    candidate_k=self.candidate_k,
                )
            except Exception as e:
                logger.warning("Retrieval failed for case %s: %s", case.id, e)
                retrieved = []

            # Determine relevant IDs based on stable document_name matching
            expected_names = {exp.document_name for exp in case.expected if exp.document_name}
            expected_slugs = {exp.document_slug for exp in case.expected if exp.document_slug}
            expected_snippets = {exp.chunk_content_snippet for exp in case.expected if exp.chunk_content_snippet}

            relevant_chunk_ids: list[str] = []
            for r in retrieved:
                is_rel = False
                if r.document_name and r.document_name in expected_names:
                    is_rel = True
                elif r.document_name and r.document_name in expected_slugs:
                    is_rel = True
                # snippet matching (if we had chunk content, we could match)
                r.is_relevant = is_rel
                if is_rel:
                    relevant_chunk_ids.append(r.chunk_id)

            # For metrics we need to know which retrieved are relevant vs expected set
            # Build relevant list as expected document_names expanded to retrieved chunk_ids that match
            # If no retrieved matches expected, relevant_ids is still expected count for recall denominator
            # We use expected_names as relevant identifiers and map retrieved to same space
            # For simplicity, use document_name as identifier
            retrieved_doc_names = [r.document_name or r.chunk_id for r in retrieved]
            relevant_doc_names = list(expected_names) if expected_names else list(expected_slugs) if expected_slugs else []

            # If expected uses chunk snippet, we treat as document-level for now (future: chunk hash)
            # Hit calculation uses document_name level
            hit_values: dict[str, bool] = {}
            for tk in top_k_values:
                hit_values[str(tk)] = EvaluationMetrics.hit_at_k(retrieved_doc_names, relevant_doc_names, tk) if relevant_doc_names else False

            # MRR etc. at primary top_k
            mrr = EvaluationMetrics.reciprocal_rank(retrieved_doc_names, relevant_doc_names) if relevant_doc_names else 0.0
            prec = EvaluationMetrics.precision_at_k(retrieved_doc_names, relevant_doc_names, top_k) if relevant_doc_names else 0.0
            rec = EvaluationMetrics.recall_at_k(retrieved_doc_names, relevant_doc_names, top_k) if relevant_doc_names else 0.0

            # First relevant rank
            first_rank: int | None = None
            for rank, doc_name in enumerate(retrieved_doc_names, start=1):
                if doc_name in set(relevant_doc_names):
                    first_rank = rank
                    break

            status = "hit" if hit_values.get(str(top_k), False) else "miss"
            if rec > 0 and not hit_values.get(str(top_k), False):
                status = "partial"

            duration_ms = (time.perf_counter() - t0) * 1000.0

            cr = CaseResult(
                case_id=case.id,
                query=case.query,
                category=case.category,
                difficulty=case.difficulty,
                expected=case.expected,
                retrieved=retrieved,
                top_k=top_k,
                hit_at_k=hit_values,
                mrr=round(mrr, 4),
                precision_at_k=round(prec, 4),
                recall_at_k=round(rec, 4),
                first_relevant_rank=first_rank,
                status=status,
                duration_ms=round(duration_ms, 2),
            )
            case_results.append(cr)
            if status == "miss":
                failures.append(cr)

            logger.debug("Case %s [%s] %s rank=%s mrr=%.3f", case.id, case.category.value, status, first_rank, mrr)

        # Aggregate
        overall = EvaluationMetrics.aggregate(case_results, top_k=top_k, top_k_values=top_k_values)
        by_category = EvaluationMetrics.aggregate_by_category(case_results, top_k=top_k)
        by_difficulty = EvaluationMetrics.aggregate_by_difficulty(case_results, top_k=top_k)

        # Worst queries: lowest MRR then no-hit
        worst = sorted(case_results, key=lambda c: (c.mrr, -c.duration_ms))[:10]

        # Config snapshot
        config = EvaluationConfigSnapshot(
            evaluation_version="1.0",
            dataset_version=ds.version,
            retriever_type=self.retriever_name,
            embedding_model=get_settings().EMBEDDING_MODEL,
            embedding_dimension=get_settings().EMBEDDING_DIMENSION,
            top_k=top_k,
            candidate_k=self.candidate_k,
            fusion_method="rrf",
            rrf_k=get_settings().RRF_K,
            extra={"top_k_values": top_k_values},
        )

        # Git commit if available
        git_commit = None
        try:
            import subprocess

            git_commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        except Exception:
            pass

        report = EvaluationReport(
            evaluation_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            dataset_version=ds.version,
            dataset_path=str(self.dataset_path),
            retriever=self.retriever_name,
            top_k=top_k,
            config=config,
            overall=overall,
            by_category=by_category,
            by_difficulty=by_difficulty,
            cases=case_results,
            failures=failures,
            worst_queries=worst,
            git_commit=git_commit,
        )
        logger.info(
            "Evaluation complete %s retriever=%s cases=%d hit@5=%.3f mrr=%.3f",
            report.evaluation_id,
            self.retriever_name,
            len(case_results),
            overall.hit_at_5,
            overall.mrr,
        )
        return report
