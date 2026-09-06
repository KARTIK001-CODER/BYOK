"""Mock verifier — deterministic for tests."""

from __future__ import annotations

import time

from app.services.verification.base import BaseVerifier
from app.services.verification.schemas import Claim, ClaimVerificationResult, Evidence, VerificationStatus


class MockVerifier(BaseVerifier):
    """Deterministic mock: simple rules for testing."""

    def __init__(self, default_status: VerificationStatus | None = None) -> None:
        self._default = default_status

    @property
    def name(self) -> str:
        return "mock"

    async def verify(self, claim: Claim, evidence: list[Evidence]) -> ClaimVerificationResult:
        t0 = time.perf_counter()
        if self._default:
            status = self._default
            conf = 0.9
            reason = f"Mock forced {status.value}"
        else:
            # Deterministic based on claim text
            lower = claim.text.lower()
            if "cannot" in lower and any("cannot" in e.content.lower() for e in evidence):
                status = VerificationStatus.SUPPORTED
            elif "90" in lower and any("30" in e.content for e in evidence):
                status = VerificationStatus.CONTRADICTED
            elif "not" in lower:
                status = VerificationStatus.CONTRADICTED if any("not" in e.content.lower() for e in evidence) else VerificationStatus.SUPPORTED
            elif not evidence:
                status = VerificationStatus.UNSUPPORTED
            elif claim.claim_type.value == "NON_VERIFIABLE":
                status = VerificationStatus.NON_VERIFIABLE
            else:
                # Default: if evidence contains any word from claim -> supported else unsupported
                status = VerificationStatus.SUPPORTED if any(w in e.content.lower() for e in evidence for w in lower.split()[:3]) else VerificationStatus.UNSUPPORTED
            conf = 0.85
            reason = "Mock deterministic"
        return ClaimVerificationResult(
            claim=claim,
            status=status,
            confidence=conf,
            reason=reason,
            evidence=evidence,
            provider=self.name,
            verification_latency_ms=round((time.perf_counter() - t0)*1000, 2),
        )
