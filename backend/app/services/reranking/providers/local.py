"""Local cross-encoder reranker — CPU, singleton, ~80MB model."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import get_settings
from app.services.reranking.base import BaseReranker

logger = logging.getLogger("app.services.reranking.providers.local")

# Singleton cache
_GLOBAL_RERANKER_MODEL: Any | None = None
_GLOBAL_RERANKER_MODEL_NAME: str | None = None
_GLOBAL_LOAD_MS: float | None = None


class LocalReranker(BaseReranker):
    """
    Local cross-encoder reranker.

    Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (default, 80M, ~340 MB RAM, CPU)
    Alternative: BAAI/bge-reranker-base (~278M) — documented but not default due to latency/memory.

    Uses sentence_transformers.CrossEncoder if available; falls back to mock lexical if not.
    """

    DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(
        self,
        model_name: str | None = None,
        max_length: int | None = None,
    ) -> None:
        settings = get_settings()
        self._model_name = model_name or getattr(settings, "RERANKER_MODEL", self.DEFAULT_MODEL)
        self._max_length = max_length or getattr(settings, "RERANKER_MAX_DOCUMENT_LENGTH", 512)
        self._model = self._get_or_load_model()

    @property
    def name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_or_load_model(self) -> Any:
        global _GLOBAL_RERANKER_MODEL, _GLOBAL_RERANKER_MODEL_NAME, _GLOBAL_LOAD_MS
        # Return cached if same model
        if _GLOBAL_RERANKER_MODEL is not None and _GLOBAL_RERANKER_MODEL_NAME == self._model_name:
            return _GLOBAL_RERANKER_MODEL

        # If cached but different model, reload
        if _GLOBAL_RERANKER_MODEL is not None and _GLOBAL_RERANKER_MODEL_NAME != self._model_name:
            logger.info("Switching reranker model %s -> %s", _GLOBAL_RERANKER_MODEL_NAME, self._model_name)
            _GLOBAL_RERANKER_MODEL = None

        if _GLOBAL_RERANKER_MODEL is None:
            t0 = time.perf_counter()
            logger.info("Initializing LocalReranker model: %s", self._model_name)
            try:
                from sentence_transformers import CrossEncoder  # type: ignore

                # Use CPU, trust_remote_code False, max_length via tokenizer kwargs
                model = CrossEncoder(self._model_name, max_length=self._max_length, device="cpu", trust_remote_code=False)
                _GLOBAL_RERANKER_MODEL = model
                _GLOBAL_RERANKER_MODEL_NAME = self._model_name
                _GLOBAL_LOAD_MS = (time.perf_counter() - t0) * 1000.0
                logger.info("LocalReranker model %s loaded in %.2f ms (warm next)", self._model_name, _GLOBAL_LOAD_MS)
            except Exception as e:
                logger.warning("Failed to load CrossEncoder %s: %s — fallback to mock lexical", self._model_name, e)
                # Store None to trigger fallback per-request; but keep name for tracing
                _GLOBAL_RERANKER_MODEL = None
                _GLOBAL_RERANKER_MODEL_NAME = self._model_name
                _GLOBAL_LOAD_MS = (time.perf_counter() - t0) * 1000.0
                # Return None sentinel — rerank will use lexical fallback
                return None
        return _GLOBAL_RERANKER_MODEL

    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []

        # If model failed to load, fallback to lexical mock
        if self._model is None:
            from app.services.reranking.providers.mock import MockReranker

            mock = MockReranker(model_name=f"{self._model_name}-fallback-mock")
            return await mock.rerank(query, candidates, top_k=top_k)

        # Prepare pairs: (query, truncated content)
        pairs: list[list[str]] = []
        for cand in candidates:
            content = cand.get("content", "") or ""
            # Truncate to max_length chars (approx, tokenizer will handle)
            if len(content) > self._max_length * 4:  # heuristic chars ~ 4* tokens
                content = content[: self._max_length * 4]
            pairs.append([query, content])

        # Run inference via to_thread to avoid blocking event loop (CPU-bound)
        t0 = time.perf_counter()
        try:
            scores: list[float] = await asyncio.to_thread(self._model.predict, pairs, batch_size=16, show_progress_bar=False)
            # Ensure list
            if hasattr(scores, "tolist"):
                scores = scores.tolist()
        except Exception as e:
            logger.warning("CrossEncoder predict failed: %s — fallback to mock", e)
            from app.services.reranking.providers.mock import MockReranker

            mock = MockReranker(model_name=f"{self._model_name}-fallback-mock")
            return await mock.rerank(query, candidates, top_k=top_k)

        _ = (time.perf_counter() - t0) * 1000.0  # caller measures

        # Merge scores
        scored: list[dict[str, Any]] = []
        for idx, (cand, score) in enumerate(zip(candidates, scores)):
            scored.append(
                {
                    **cand,
                    "rerank_score": float(score),
                    "original_rank": cand.get("retrieval_rank") or idx + 1,
                }
            )

        scored.sort(key=lambda x: (-x["rerank_score"], x["original_rank"]))

        result: list[dict[str, Any]] = []
        for rank, item in enumerate(scored[:top_k], start=1):
            result.append({**item, "rerank_rank": rank})
        return result

    @staticmethod
    def is_warm() -> bool:
        return _GLOBAL_RERANKER_MODEL is not None

    @staticmethod
    def load_ms() -> float | None:
        return _GLOBAL_LOAD_MS
