"""Factory for rerankers — mirrors LLM and embedding factories."""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.services.reranking.base import BaseReranker
from app.services.reranking.providers.local import LocalReranker
from app.services.reranking.providers.mock import MockReranker

logger = logging.getLogger("app.services.reranking.factory")


class RerankerFactory:
    """Create reranker instances by provider name."""

    _mock_instance: MockReranker | None = None

    @classmethod
    def set_mock_provider(cls, mock: MockReranker | None) -> None:
        cls._mock_instance = mock

    @classmethod
    def create(cls, provider: str | None = None, model: str | None = None) -> BaseReranker:
        settings = get_settings()
        prov = (provider or getattr(settings, "RERANKER_PROVIDER", "local")).strip().lower()

        if prov == "mock":
            return cls._mock_instance or MockReranker(model_name=model or "mock-cross-encoder")
        if prov == "local":
            return LocalReranker(model_name=model or getattr(settings, "RERANKER_MODEL", LocalReranker.DEFAULT_MODEL))
        # Future: Cohere, API etc. — for now fallback to local
        logger.warning("Unknown reranker provider %s, fallback to local", prov)
        return LocalReranker(model_name=model or getattr(settings, "RERANKER_MODEL", LocalReranker.DEFAULT_MODEL))
