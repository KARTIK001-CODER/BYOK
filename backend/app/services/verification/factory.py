"""Factories for claim extractor and verifier."""

from __future__ import annotations

from app.core.config import get_settings
from app.services.verification.base import BaseClaimExtractor, BaseVerifier
from app.services.verification.claim_extraction import RuleBasedClaimExtractor
from app.services.verification.providers.heuristic import HeuristicVerifier
from app.services.verification.providers.llm import LLMVerifier
from app.services.verification.providers.mock import MockVerifier


class ClaimExtractorFactory:
    _mock = None

    @classmethod
    def create(cls, provider: str | None = None) -> BaseClaimExtractor:
        prov = (provider or "rule_based").lower()
        if prov == "mock":
            # Mock uses rule-based but deterministic
            return RuleBasedClaimExtractor()
        # LLM claim extractor future
        return RuleBasedClaimExtractor()


class VerifierFactory:
    _mock_instance: MockVerifier | None = None

    @classmethod
    def set_mock(cls, mock: MockVerifier | None) -> None:
        cls._mock_instance = mock

    @classmethod
    def create(cls, provider: str | None = None) -> BaseVerifier:
        settings = get_settings()
        prov = (provider or getattr(settings, "VERIFIER_PROVIDER", "heuristic")).lower()
        if prov == "mock":
            return cls._mock_instance or MockVerifier()
        if prov == "llm":
            return LLMVerifier()
        # heuristic is default
        return HeuristicVerifier()
