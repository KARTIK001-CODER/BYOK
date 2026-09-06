"""Base interfaces for verification providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.verification.schemas import Claim, ClaimVerificationResult, Evidence


class BaseClaimExtractor(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def extract(self, answer: str) -> list[Claim]:
        ...


class BaseVerifier(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def verify(
        self,
        claim: Claim,
        evidence: list[Evidence],
    ) -> ClaimVerificationResult:
        ...
