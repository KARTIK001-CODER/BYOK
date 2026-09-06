"""LLM verifier — optional, structured output, evidence-only principle."""

from __future__ import annotations

import json
import logging
import time

from app.core.config import get_settings
from app.services.llm.base import LLMMessage, LLMRequest
from app.services.llm.factory import LLMProviderFactory
from app.services.verification.base import BaseVerifier
from app.services.verification.schemas import Claim, ClaimVerificationResult, Evidence, VerificationStatus
from pydantic import BaseModel, Field

logger = logging.getLogger("app.services.verification.providers.llm")


class LLMVerifierOutput(BaseModel):
    status: VerificationStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class LLMVerifier(BaseVerifier):
    """LLM judge — evidence-only, no external knowledge."""

    def __init__(self, model: str | None = None, provider: str | None = None) -> None:
        settings = get_settings()
        self._provider_name = provider or settings.DEFAULT_LLM_PROVIDER
        self._model = model or settings.DEFAULT_LLM_MODEL

    @property
    def name(self) -> str:
        return "llm"

    async def verify(self, claim: Claim, evidence: list[Evidence]) -> ClaimVerificationResult:
        t0 = time.perf_counter()
        if not evidence:
            return ClaimVerificationResult(
                claim=claim,
                status=VerificationStatus.UNSUPPORTED,
                confidence=0.6,
                reason="No evidence",
                evidence=[],
                provider=self.name,
                verification_latency_ms=round((time.perf_counter() - t0)*1000, 2),
            )

        # Build evidence block
        evidence_block = "\n\n".join(f"[Evidence {i+1}] {e.content[:800]}" for i, e in enumerate(evidence))
        system_prompt = (
            "You are a strict evidence verifier. ONLY use the provided evidence to classify the claim. "
            "Do NOT use external knowledge. Respond with JSON containing status (SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, CONTRADICTED, UNCERTAIN), confidence 0.0-1.0, and reason."
        )
        user_prompt = f"Claim: {claim.text}\n\nEvidence:\n{evidence_block}\n\nClassify whether evidence supports the claim."

        provider, model = LLMProviderFactory.create(provider=self._provider_name, model=self._model)
        req = LLMRequest(
            provider=provider.name,
            model=model,
            messages=[LLMMessage(role="system", content=system_prompt), LLMMessage(role="user", content=user_prompt)],
            temperature=0.0,
            max_tokens=256,
            stream=False,
        )
        try:
            resp = await provider.generate(req)
            # Try parse JSON
            content = resp.content.strip()
            # Extract JSON if wrapped
            if "{" in content:
                content = content[content.find("{") : content.rfind("}") + 1]
            parsed = json.loads(content)
            out = LLMVerifierOutput.model_validate(parsed)
            status = out.status
            conf = out.confidence
            reason = out.reason
        except Exception as e:
            logger.warning("LLM verifier failed: %s", e)
            # Fallback to uncertain
            status = VerificationStatus.UNCERTAIN
            conf = 0.4
            reason = f"LLM verifier fallback: {e}"

        latency = round((time.perf_counter() - t0)*1000, 2)
        return ClaimVerificationResult(
            claim=claim,
            status=status,
            confidence=conf,
            reason=reason,
            evidence=evidence,
            provider=self.name,
            verification_latency_ms=latency,
        )
