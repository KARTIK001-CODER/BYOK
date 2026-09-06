"""Deterministic mock reranker — for tests, benchmarks, and pipeline verification."""

from __future__ import annotations

import re
from typing import Any

from app.services.reranking.base import BaseReranker


class MockReranker(BaseReranker):
    """Deterministic rule: score = lexical overlap + position bonus. No randomness."""

    def __init__(self, model_name: str = "mock-cross-encoder") -> None:
        self._model_name = model_name

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    @staticmethod
    def _lexical_score(query: str, content: str) -> float:
        q_terms = set(re.findall(r"\b\w+\b", query.lower()))
        c_terms = set(re.findall(r"\b\w+\b", content.lower()))
        if not q_terms:
            return 0.0
        overlap = len(q_terms.intersection(c_terms)) / len(q_terms)
        # bonus for exact phrase
        phrase_bonus = 0.3 if query.lower().strip() in content.lower() else 0.0
        # bonus for title-like terms
        return overlap + phrase_bonus

    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for idx, cand in enumerate(candidates):
            content = cand.get("content", "")
            base = self._lexical_score(query, content)
            # Slight position decay to simulate original rank influence but deterministic
            position_bonus = 0.01 * (len(candidates) - idx) / len(candidates) if candidates else 0
            score = base + position_bonus
            scored.append({**cand, "rerank_score": round(score, 4), "original_rank": cand.get("retrieval_rank") or idx + 1})

        # Sort descending by rerank_score, tie-break by original rank
        scored.sort(key=lambda x: (-x["rerank_score"], x["original_rank"]))

        # Assign rerank_rank and truncate
        result: list[dict[str, Any]] = []
        for rank, item in enumerate(scored[:top_k], start=1):
            result.append({**item, "rerank_rank": rank})
        return result
