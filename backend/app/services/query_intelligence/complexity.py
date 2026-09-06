"""Query complexity — deterministic, reused by retrieval_intelligence."""

from app.services.query_intelligence.schemas import QueryFeatures

def complexity_from_features(features: QueryFeatures, ambiguity_score: float = 0.0) -> str:
    wc = features.word_count
    lower = features.normalized_query.lower()
    # Multi-hop signals
    if any(kw in lower for kw in [" and ", " affect ", " impact ", " based on ", " across ", " then "]) and wc >= 10:
        return "MULTI_HOP"
    if any(w in lower for w in ["compare", "difference", "between", "versus", "vs"]):
        return "COMPLEX"
    if wc <= 6:
        return "SIMPLE"
    if wc <= 12:
        return "MODERATE"
    return "COMPLEX"
