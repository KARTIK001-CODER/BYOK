"""Ambiguity analysis — deterministic weighted rules, 0.0-1.0 score."""

from __future__ import annotations

import re

from app.services.query_intelligence.schemas import AmbiguityAnalysis, QueryFeatures

# Generic vague signals
PRONOUNS = {"it", "this", "that", "they", "them", "he", "she", "you", "we", "these", "those"}
GENERIC_VERBS = {"do", "does", "is", "are", "work", "happen", "get", "make", "take", "tell", "show", "give"}
GENERIC_NOUNS = {"thing", "things", "stuff", "something", "anything", "policy", "limits", "help", "work", "it"}
CONTEXT_REFERENCES = {"that", "this", "it", "there", "then", "more", "again", "other"}
VERY_SHORT_THRESHOLD = 4  # words

# Weights for ambiguity score (heuristic, not ML)
WEIGHTS = {
    "very_short": 0.35,
    "pronoun_without_noun": 0.25,
    "generic_verb": 0.15,
    "generic_noun": 0.10,
    "context_reference": 0.20,
    "missing_entities": 0.15,
    "single_word": 0.40,
    "only_question_word": 0.30,
}


def analyze_ambiguity(features: QueryFeatures) -> AmbiguityAnalysis:
    normalized = features.normalized_query.lower()
    words = re.findall(r"\b\w+\b", normalized)
    word_count = len(words)
    signals: list[str] = []
    reasons: list[str] = []
    score = 0.0

    # Very short query
    if word_count <= VERY_SHORT_THRESHOLD:
        signals.append("very_short")
        reasons.append(f"word_count={word_count} <= {VERY_SHORT_THRESHOLD}")
        score += WEIGHTS["very_short"]
        if word_count <= 2:
            signals.append("single_word" if word_count == 1 else "two_words")
            score += WEIGHTS["single_word"] * 0.5 if word_count == 1 else 0.15

    # Pronouns without explicit nouns — check if pronouns exist and no capitalized entities / identifiers
    pronoun_count = sum(1 for w in words if w in PRONOUNS)
    if pronoun_count > 0:
        # If no capitalized terms and no identifiers, pronoun is ambiguous
        if not features.capitalized_terms and not features.contains_identifier and not features.identifier_candidates:
            signals.append("pronoun_without_noun")
            reasons.append(f"pronoun_count={pronoun_count} without entities")
            score += WEIGHTS["pronoun_without_noun"]
        # Generic context reference
        if any(w in CONTEXT_REFERENCES for w in words):
            signals.append("context_reference")
            reasons.append("context_reference word present")
            score += WEIGHTS["context_reference"] * 0.5

    # Generic verbs
    generic_verb_hits = sum(1 for w in words if w in GENERIC_VERBS)
    if generic_verb_hits > 0 and word_count <= 6:
        # "How does it work?" -> generic verbs dominate
        ratio = generic_verb_hits / max(1, word_count)
        if ratio >= 0.5:
            signals.append("generic_verb")
            reasons.append(f"generic_verb_ratio {ratio:.2f}")
            score += WEIGHTS["generic_verb"]

    # Generic nouns
    generic_noun_hits = sum(1 for w in words if w in GENERIC_NOUNS)
    if generic_noun_hits > 0 and word_count <= 6:
        signals.append("generic_noun")
        reasons.append(f"generic_noun {generic_noun_hits}")
        score += WEIGHTS["generic_noun"]

    # Missing entities: no capitalized, no identifier, no numbers, no special terms, but question word present
    has_entity = bool(
        features.capitalized_terms
        or features.contains_identifier
        or features.contains_numbers
        or features.contains_special_terms
        or features.uppercase_terms
    )
    if not has_entity and features.contains_question_word and word_count <= 8:
        signals.append("missing_entities")
        reasons.append("no entities despite question")
        score += WEIGHTS["missing_entities"]

    # Only question word + pronouns (e.g., "How does it work?")
    if word_count <= 5 and features.contains_question_word and pronoun_count > 0 and not has_entity:
        signals.append("only_question_word")
        reasons.append("short question with pronoun, no entity")
        score += WEIGHTS["only_question_word"]

    # Clamp
    ambiguity_score = min(1.0, max(0.0, score))
    # Deduplicate signals
    signals = list(dict.fromkeys(signals))
    is_ambiguous = ambiguity_score >= 0.5

    return AmbiguityAnalysis(
        is_ambiguous=is_ambiguous,
        ambiguity_score=round(ambiguity_score, 3),
        signals=signals,
        reasons=reasons,
    )
