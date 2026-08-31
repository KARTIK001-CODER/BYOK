from typing import Any

from app.models.document_chunk import DocumentChunk
from app.services.retrieval.schemas import ChunkProvenance, RetrievalResult


class CandidateMatch:
    """Internal candidate match representation from a specific retriever."""

    def __init__(
        self,
        chunk: DocumentChunk,
        score: float,
        rank: int,
        source: str,
    ) -> None:
        self.chunk = chunk
        self.score = score
        self.rank = rank  # 1-indexed
        self.source = source


class ReciprocalRankFusion:
    """
    Deterministic Reciprocal Rank Fusion (RRF) algorithm.

    Formula:
        RRF(d) = sum( 1.0 / (k + rank_m(d)) ) for each retriever list m where d appears.

    where:
        k = smoothing constant (default: 60)
        rank_m(d) = 1-based rank position of chunk d in ranking m
    """

    def __init__(self, rrf_k: int = 60) -> None:
        if rrf_k <= 0:
            raise ValueError(f"RRF smoothing constant k must be positive, got {rrf_k}")
        self.rrf_k = rrf_k

    def fuse(
        self,
        vector_candidates: list[CandidateMatch],
        keyword_candidates: list[CandidateMatch],
        top_k: int = 10,
    ) -> list[RetrievalResult]:
        """
        Combine and deduplicate ranked candidates from vector and keyword search.

        Args:
            vector_candidates: Ranked candidate matches from vector retriever.
            keyword_candidates: Ranked candidate matches from keyword retriever.
            top_k: Number of highest-ranked results to return.

        Returns:
            list[RetrievalResult]: Top-K deduplicated, fused results sorted by RRF score descending.
        """
        # Map: chunk_id -> dict with accumulated RRF score, chunk,
        # vector_score, keyword_score, sources
        fused_map: dict[str, dict[str, Any]] = {}

        # 1. Process vector candidates
        for idx, candidate in enumerate(vector_candidates, start=1):
            chunk = candidate.chunk
            chunk_id = chunk.id
            rrf_score_contribution = 1.0 / (self.rrf_k + idx)

            if chunk_id not in fused_map:
                fused_map[chunk_id] = {
                    "chunk": chunk,
                    "rrf_score": rrf_score_contribution,
                    "vector_score": candidate.score,
                    "keyword_score": None,
                    "sources": {"vector"},
                }
            else:
                fused_map[chunk_id]["rrf_score"] += rrf_score_contribution
                fused_map[chunk_id]["vector_score"] = candidate.score
                fused_map[chunk_id]["sources"].add("vector")

        # 2. Process keyword candidates
        for idx, candidate in enumerate(keyword_candidates, start=1):
            chunk = candidate.chunk
            chunk_id = chunk.id
            rrf_score_contribution = 1.0 / (self.rrf_k + idx)

            if chunk_id not in fused_map:
                fused_map[chunk_id] = {
                    "chunk": chunk,
                    "rrf_score": rrf_score_contribution,
                    "vector_score": None,
                    "keyword_score": candidate.score,
                    "sources": {"keyword"},
                }
            else:
                fused_map[chunk_id]["rrf_score"] += rrf_score_contribution
                fused_map[chunk_id]["keyword_score"] = candidate.score
                fused_map[chunk_id]["sources"].add("keyword")

        # 3. Sort candidates by RRF score descending (stable tie-breaking by chunk_id)
        sorted_items = sorted(
            fused_map.values(),
            key=lambda item: (-item["rrf_score"], item["chunk"].id),
        )

        # 4. Truncate to top_k and build RetrievalResult with full provenance
        results: list[RetrievalResult] = []
        for rank, item in enumerate(sorted_items[:top_k], start=1):
            chunk: DocumentChunk = item["chunk"]
            sources = item["sources"]
            source_label = "hybrid" if len(sources) > 1 else next(iter(sources))

            provenance = ChunkProvenance(
                organization_id=chunk.organization_id,
                knowledge_base_id=chunk.knowledge_base_id,
                document_id=chunk.document_id,
                document_version_id=chunk.document_version_id,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                metadata=chunk.chunk_metadata,
            )

            result = RetrievalResult(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_version_id=chunk.document_version_id,
                knowledge_base_id=chunk.knowledge_base_id,
                content=chunk.content,
                score=round(item["rrf_score"], 6),
                rank=rank,
                source=source_label,
                vector_score=round(item["vector_score"], 4)
                if item["vector_score"] is not None
                else None,
                keyword_score=round(item["keyword_score"], 4)
                if item["keyword_score"] is not None
                else None,
                rrf_score=round(item["rrf_score"], 6),
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                metadata=chunk.chunk_metadata,
                provenance=provenance,
            )
            results.append(result)

        return results
