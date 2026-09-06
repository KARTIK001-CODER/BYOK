"""Heuristic verifier — lexical, numeric, temporal, negation."""

from __future__ import annotations

import re
import time

from app.services.verification.base import BaseVerifier
from app.services.verification.schemas import Claim, ClaimVerificationResult, Evidence, VerificationStatus


NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
NEGATION_WORDS = {"not", "no", "never", "cannot", "can't", "won't", "without", "against", "prohibited", "cannot", "unable", "failed"}
CONTRAST_WORDS = {"but", "however", "although", "though"}


def _extract_numbers(text: str) -> set[str]:
    return set(NUM_RE.findall(text))


def _has_negation(text: str) -> bool:
    lower = text.lower()
    return any(w in lower.split() or f" {w} " in f" {lower} " for w in NEGATION_WORDS)


def _lexical_overlap(a: str, b: str) -> float:
    a_terms = set(re.findall(r"\b\w+\b", a.lower()))
    b_terms = set(re.findall(r"\b\w+\b", b.lower()))
    if not a_terms:
        return 0.0
    return len(a_terms.intersection(b_terms)) / len(a_terms)


class HeuristicVerifier(BaseVerifier):
    """Fast deterministic verifier — no LLM. High confidence only when clear."""

    @property
    def name(self) -> str:
        return "heuristic"

    async def verify(self, claim: Claim, evidence: list[Evidence]) -> ClaimVerificationResult:
        t0 = time.perf_counter()
        if claim.claim_type.value == "NON_VERIFIABLE":
            return ClaimVerificationResult(
                claim=claim,
                status=VerificationStatus.NON_VERIFIABLE,
                confidence=0.95,
                reason="Non-verifiable opinion/subjective",
                evidence=evidence,
                provider=self.name,
                verification_latency_ms=round((time.perf_counter() - t0)*1000, 2),
            )

        if not evidence:
            return ClaimVerificationResult(
                claim=claim,
                status=VerificationStatus.UNSUPPORTED,
                confidence=0.7,
                reason="No evidence selected",
                evidence=[],
                provider=self.name,
                verification_latency_ms=round((time.perf_counter() - t0)*1000, 2),
            )

        # For each evidence, compute signals
        # Aggregate: if any evidence clearly supports -> SUPPORTED, if any contradicts -> CONTRADICTED, else UNSUPPORTED/UNCERTAIN
        claim_lower = claim.text.lower()
        claim_numbers = _extract_numbers(claim.text)
        claim_neg = _has_negation(claim.text)

        best_status = VerificationStatus.UNSUPPORTED
        best_conf = 0.0
        best_reason = "No evidence supports claim"

        # Debug for numerical contradiction test
        # print(f"DEBUG claim_numbers={claim_numbers} ev_numbers={ev_numbers if evidence else None} overlap for first ev={( _lexical_overlap(claim.text, evidence[0].content) if evidence else 'no_ev')}")

        for ev in evidence:
            ev_lower = ev.content.lower()
            ev_numbers = _extract_numbers(ev.content)
            ev_neg = _has_negation(ev.content)
            overlap = _lexical_overlap(claim.text, ev.content)

            # Numerical contradiction: claim has number not in evidence, and evidence has different number
            if claim_numbers:
                # If claim numbers and evidence numbers exist but don't intersect -> potential contradiction
                if claim_numbers and ev_numbers and not claim_numbers.intersection(ev_numbers):
                    # Check if both mention same context (refund, days, etc.) — very low threshold for numerical
                    if overlap >= 0.1:  # sufficient lexical overlap to be same topic (lower for numerical, stem variant)
                        best_status = VerificationStatus.CONTRADICTED
                        best_conf = 0.85
                        best_reason = f"Numerical mismatch: claim {claim_numbers} vs evidence {ev_numbers}"
                        break

            # Negation contradiction: one has negation other doesn't, with high overlap
            if claim_neg != ev_neg and overlap >= 0.5:
                best_status = VerificationStatus.CONTRADICTED
                best_conf = 0.80
                best_reason = "Negation mismatch with high lexical overlap"
                break

            # Lexical support — tuned for paraphrase (lower thresholds)
            if overlap >= 0.5:
                # High overlap -> SUPPORTED (paraphrase still 0.5+)
                if overlap >= 0.65:
                    best_status = VerificationStatus.SUPPORTED
                    best_conf = max(best_conf, 0.85)
                    best_reason = f"High lexical overlap {overlap:.2f}"
                else:
                    # Partial
                    if best_status not in (VerificationStatus.SUPPORTED, VerificationStatus.CONTRADICTED):
                        best_status = VerificationStatus.PARTIALLY_SUPPORTED
                        best_conf = max(best_conf, 0.65)
                        best_reason = f"Partial overlap {overlap:.2f}"
            elif overlap >= 0.3:
                if best_status in (VerificationStatus.UNSUPPORTED, VerificationStatus.UNCERTAIN):
                    best_status = VerificationStatus.PARTIALLY_SUPPORTED
                    best_conf = max(best_conf, 0.55)
                    best_reason = f"Moderate overlap {overlap:.2f}"
            else:
                # Low overlap remains UNSUPPORTED
                if best_status == VerificationStatus.UNSUPPORTED:
                    best_conf = max(best_conf, 0.60)

        # If still unsupported but overlap was moderate, mark uncertain
        if best_status == VerificationStatus.UNSUPPORTED and best_conf < 0.5:
            best_status = VerificationStatus.UNCERTAIN
            best_conf = 0.45
            best_reason = "Insufficient evidence to confidently classify"

        # Confidence based on overlap, negation, numerical
        latency = round((time.perf_counter() - t0)*1000, 2)
        return ClaimVerificationResult(
            claim=claim,
            status=best_status,
            confidence=round(best_conf, 2),
            reason=best_reason,
            evidence=evidence,
            provider=self.name,
            verification_latency_ms=latency,
        )
