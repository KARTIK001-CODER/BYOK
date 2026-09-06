"""Base reranker interface — future providers (local, mock, Cohere, API) plug here."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseReranker(ABC):
    """Protocol for rerankers. Implementations must be async-safe and not block event loop internally."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Rerank candidates.

        Args:
            query: Original user query.
            candidates: List of dicts with at least chunk_id, document_name, content, retrieval_score/rank.
            top_k: Number of top results to return after reranking.

        Returns:
            List of dicts sorted by rerank_score descending, each with original_rank, rerank_score, rerank_rank.
        """
        ...
