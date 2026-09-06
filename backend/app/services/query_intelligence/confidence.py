"""Retrieval confidence — top score, gap, count."""

from typing import Any

def retrieval_confidence(results: list[Any], top_k: int = 5) -> dict[str, Any]:
    if not results:
        return {"confidence": 0.0, "top_score": None, "score_gap": None, "result_count": 0, "reason": "no_results"}
    top_score = max((r.score for r in results), default=0.0)
    sorted_scores = sorted([r.score for r in results], reverse=True)
    gap = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0.0
    count = len(results)
    if top_score >= 0.8 and gap >= 0.1 and count >= 3:
        conf, reason = 0.9, "high_top_score_and_gap"
    elif top_score >= 0.6 and count >= 2:
        conf, reason = 0.7, "moderate_top_score"
    elif top_score < 0.4:
        conf, reason = 0.2, "low_top_score"
    else:
        conf, reason = 0.5, "medium"
    return {"confidence": conf, "top_score": top_score, "score_gap": gap, "result_count": count, "reason": reason}
