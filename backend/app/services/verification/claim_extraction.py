"""Deterministic claim extraction — rule-based, sentence-based, no LLM by default."""

from __future__ import annotations

import re
import uuid

from app.services.verification.base import BaseClaimExtractor
from app.services.verification.schemas import Claim, ClaimType

# Simple sentence splitter
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Heuristics for claim type
NUMERIC_RE = re.compile(r"\b\d+(\.\d+)?\s*(%|days?|months?|years?|EUR|USD|€|MB|GB|chunks?)\b", re.I)
TEMPORAL_RE = re.compile(r"\b(19|20)\d{2}|January|February|March|April|May|June|July|August|September|October|November|December|today|tomorrow|yesterday\b", re.I)
POLICY_RE = re.compile(r"\b(must|should|required|cancellation|refund|policy|request|submit|contact)\b", re.I)
NON_VERIFIABLE_RE = re.compile(r"\b(excellent|great|best|wonderful|amazing|I think|opinion)\b", re.I)


def classify_claim_type(text: str) -> ClaimType:
    t = text.strip()
    if NON_VERIFIABLE_RE.search(t):
        return ClaimType.NON_VERIFIABLE
    if NUMERIC_RE.search(t):
        return ClaimType.NUMERICAL
    if TEMPORAL_RE.search(t):
        # Temporal if date-like and not already numerical
        if re.search(r"\b(19|20)\d{2}\b", t):
            return ClaimType.TEMPORAL
        # If contains duration, treat as numerical
        if NUMERIC_RE.search(t):
            return ClaimType.NUMERICAL
    if POLICY_RE.search(t):
        return ClaimType.POLICY
    if " is " in t.lower() and len(t.split()) <= 12:
        return ClaimType.FACTUAL
    # Default
    return ClaimType.FACTUAL


class RuleBasedClaimExtractor(BaseClaimExtractor):
    """Deterministic sentence-based extractor. No LLM, <5ms for 20 claims."""

    @property
    def name(self) -> str:
        return "rule_based"

    async def extract(self, answer: str) -> list[Claim]:
        if not answer or not answer.strip():
            return []
        # Split into sentences, keep spans
        sentences = []
        # Use regex finditer to preserve spans
        last_end = 0
        for m in SENT_SPLIT.finditer(answer.strip() + " "):
            # Actually split manually to get spans
            pass

        # Simple split preserving spans via search
        parts = SENT_SPLIT.split(answer.strip())
        claims: list[Claim] = []
        search_pos = 0
        for part in parts:
            text = part.strip()
            if not text or len(text) < 5:
                continue
            # Filter non-verifiable very short or generic?
            # Keep all for now, but mark NON_VERIFIABLE
            start = answer.find(text, search_pos)
            end = start + len(text) if start != -1 else None
            search_pos = (end or 0) + 1
            ctype = classify_claim_type(text)
            # Skip pure citations like "[1]"?
            if re.match(r"^\s*\[\d+\]\s*$", text):
                continue
            claims.append(
                Claim(
                    claim_id=f"claim_{len(claims)+1:03d}_{uuid.uuid4().hex[:4]}",
                    text=text,
                    claim_type=ctype,
                    answer_start=start if start != -1 else None,
                    answer_end=end,
                    importance=1,
                )
            )
        return claims
