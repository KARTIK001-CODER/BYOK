"""Evidence selection — prefer already retrieved context, no DB re-search."""

from __future__ import annotations

import re
import time

from app.services.verification.schemas import Claim, Evidence


def _lexical_overlap(a: str, b: str) -> float:
    a_terms = set(re.findall(r"\b\w+\b", a.lower()))
    b_terms = set(re.findall(r"\b\w+\b", b.lower()))
    if not a_terms:
        return 0.0
    return len(a_terms.intersection(b_terms)) / len(a_terms)


class EvidenceSelector:
    """Select top evidence per claim from already retrieved chunks. No DB query."""

    @staticmethod
    def select(
        claim: Claim,
        candidates: list[Evidence],
        top_k: int = 3,
    ) -> tuple[list[Evidence], float]:
        t0 = time.perf_counter()
        if not candidates:
            return [], 0.0
        # Score by lexical overlap + retrieval rank bonus (lower rank better)
        scored: list[tuple[float, Evidence]] = []
        for ev in candidates:
            overlap = _lexical_overlap(claim.text, ev.content)
            # Bonus for already high retrieval rank (1 is best)
            rank_bonus = 0.05 * (1.0 / (ev.retrieval_rank or 10))
            score = overlap + rank_bonus
            scored.append((score, ev))
        scored.sort(key=lambda x: -x[0])
        selected = [ev for _, ev in scored[:top_k]]
        ms = (time.perf_counter() - t0) * 1000.0
        return selected, ms
