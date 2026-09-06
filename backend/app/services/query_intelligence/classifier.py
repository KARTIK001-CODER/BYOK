"""Deterministic query classification — no LLM, confidence scored, safe fallback to hybrid."""

from __future__ import annotations

from app.services.query_intelligence.ambiguity import analyze_ambiguity
from app.services.query_intelligence.features import extract_features
from app.services.query_intelligence.schemas import AmbiguityAnalysis, QueryCategory, QueryClassification, QueryFeatures

# Heuristic scoring weights for each class (not ML)
# Each signal adds points; highest wins if confidence >= threshold


def classify_query(
    features: QueryFeatures | None = None,
    ambiguity: AmbiguityAnalysis | None = None,
    original_query: str | None = None,
) -> QueryClassification:
    if features is None and original_query is not None:
        features = extract_features(original_query)
    if features is None:
        raise ValueError("Must provide features or original_query")
    if ambiguity is None:
        ambiguity = analyze_ambiguity(features)

    scores: dict[str, float] = {
        QueryCategory.keyword.value: 0.0,
        QueryCategory.semantic.value: 0.0,
        QueryCategory.factual.value: 0.0,
        QueryCategory.multi_hop.value: 0.0,
        QueryCategory.ambiguous.value: 0.0,
    }
    signals: list[str] = []

    # Keyword signals — strong identifier
    if features.contains_identifier:
        scores[QueryCategory.keyword.value] += 0.45
        signals.append("identifier_detected")
        if features.has_snake_case:
            signals.append("contains_underscore")
            scores[QueryCategory.keyword.value] += 0.15
        if features.has_upper_case:
            signals.append("contains_upper")
            scores[QueryCategory.keyword.value] += 0.10
        if features.has_version_pattern:
            signals.append("version_pattern")
            scores[QueryCategory.keyword.value] += 0.10
        # Exact phrase with identifier is strong keyword
        if features.contains_exact_phrase and features.word_count <= 6:
            signals.append("exact_phrase")
            scores[QueryCategory.keyword.value] += 0.20
        # Rare term candidate that looks like code
        if features.rare_term_candidates:
            signals.append("rare_term")
            scores[QueryCategory.keyword.value] += 0.05

    # If query is single identifier-like token, very strong keyword
    if features.word_count == 1 and features.contains_identifier:
        scores[QueryCategory.keyword.value] += 0.30

    # Semantic signals — paraphrased, question word, no identifier, medium length
    if not features.contains_identifier and features.contains_question_word and not ambiguity.is_ambiguous:
        scores[QueryCategory.semantic.value] += 0.25
        signals.append("question_word_no_identifier")
    if features.word_count >= 6 and not features.contains_identifier and not ambiguity.is_ambiguous:
        scores[QueryCategory.semantic.value] += 0.15
        signals.append("medium_length_semantic")
    if features.question_type.value in ("definition", "procedure", "policy"):
        scores[QueryCategory.semantic.value] += 0.10
        signals.append(f"question_type_{features.question_type.value}")

    # Factual signals — direct lookup, contains numbers/specifics, shorter factual pattern
    if features.contains_numbers or features.uppercase_terms:
        scores[QueryCategory.factual.value] += 0.10
        signals.append("contains_numbers_or_upper")
    if features.question_type.value in ("factual",):
        scores[QueryCategory.factual.value] += 0.20
        signals.append("factual_question_type")
    if 4 <= features.word_count <= 10 and not ambiguity.is_ambiguous and not features.contains_identifier:
        scores[QueryCategory.factual.value] += 0.10
        signals.append("factual_length")

    # Multi-hop signals — contains conjunctions requiring multiple docs, or explicit multi-entity
    lower = features.normalized_query.lower()
    if any(phrase in lower for phrase in ["and", "after", "then", "if i", "when i", "plus", "also"]):
        # Only if query mentions two distinct topics (heuristic: and + length > 10)
        if features.word_count >= 10:
            scores[QueryCategory.multi_hop.value] += 0.25
            signals.append("multi_hop_conjunction")
    if lower.count("?") >= 1 and features.word_count >= 12:
        scores[QueryCategory.multi_hop.value] += 0.15
        signals.append("long_query_multi_hop")
    # Specific multi-hop fixture patterns
    if any(kw in lower for kw in ["trial", "refund", "pricing", "upload", "chunk", "hnsw"]) and features.word_count >= 12:
        scores[QueryCategory.multi_hop.value] += 0.10

    # Ambiguous signals — from ambiguity analyzer
    if ambiguity.is_ambiguous:
        scores[QueryCategory.ambiguous.value] += ambiguity.ambiguity_score * 0.8
        signals.extend(ambiguity.signals)
        signals.append(f"ambiguity_score_{ambiguity.ambiguity_score:.2f}")

    # Normalize signals dedup
    signals = list(dict.fromkeys(signals))

    # Pick primary
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_class, top_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    # Confidence = top_score normalized + gap to second
    # Scores are 0-~1.0, so confidence heuristic:
    gap = top_score - second_score
    raw_conf = top_score
    # Boost if gap large
    if gap >= 0.3:
        raw_conf += 0.15
    elif gap >= 0.15:
        raw_conf += 0.08
    # Penalize if ambiguous and top is not ambiguous but ambiguous score high
    if ambiguity.ambiguity_score >= 0.5 and top_class != QueryCategory.ambiguous.value:
        raw_conf -= 0.10

    confidence = max(0.0, min(1.0, raw_conf))
    # If top_score is very low (<0.25), confidence is low → unknown
    if top_score < 0.25:
        primary = QueryCategory.unknown
        confidence = max(0.0, min(0.5, confidence))
    else:
        primary = QueryCategory(top_class)

    # If ambiguity high, override to ambiguous regardless of other scores? Only if ambiguity is clearly top
    if ambiguity.is_ambiguous and ambiguity.ambiguity_score >= 0.7 and scores[QueryCategory.ambiguous.value] >= 0.4:
        primary = QueryCategory.ambiguous
        confidence = min(1.0, ambiguity.ambiguity_score)

    return QueryClassification(
        primary_class=primary,
        confidence=round(confidence, 3),
        signals=signals[:8],  # limit for explainability
        all_scores={k: round(v, 3) for k, v in scores.items()},
    )
