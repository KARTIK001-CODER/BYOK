"""Deterministic feature extraction — no LLM, no DB, <2ms target."""

from __future__ import annotations

import re
from typing import Any

from app.services.query_intelligence.schemas import QueryFeatures, QuestionType

# Pre-compiled patterns for speed
RE_SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
RE_CAMEL = re.compile(r"\b[a-z]+[A-Z][a-zA-Z0-9]*\b")
RE_UPPER_UNDERSCORE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
RE_VERSION = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")
RE_IDENTIFIER = re.compile(r"\b(?:[A-Za-z]*[_\-][A-Za-z0-9_\-]+|[A-Z]{2,}[A-Z0-9_]*|[a-z]+[A-Z][a-zA-Z0-9]*)\b")
RE_QUOTES = re.compile(r'["\'`‘’“”]')
RE_BACKTICK = re.compile(r"`[^`]+`")
RE_NUMBER = re.compile(r"\d")
RE_PUNCT = re.compile(r"[^\w\s]")
RE_UPPER_WORD = re.compile(r"\b[A-Z]{2,}\b")
RE_CAPITALIZED = re.compile(r"\b[A-Z][a-z]+\b")
RE_RARE = re.compile(r"\b\w{8,}\b")  # heuristic rare long token

QUESTION_WORDS = {"what", "how", "where", "when", "who", "why", "which", "can", "does", "is", "are", "should", "will", "did"}
PROCEDURE_PREFIXES = ("how do", "how does", "how to", "how can", "steps to", "procedure")
DEFINITION_PREFIXES = ("what is", "what does", "what are", "define", "explain")
POLICY_PREFIXES = ("refund", "policy", "cancellation", "pricing", "privacy", "handbook")
TROUBLESHOOTING_KEYWORDS = {"error", "err_", "fail", "bug", "issue", "not working", "cannot", "unable"}


def detect_question_type(normalized: str) -> QuestionType:
    lower = normalized.lower().strip()
    if any(lower.startswith(p) for p in PROCEDURE_PREFIXES):
        return QuestionType.procedure
    if any(lower.startswith(p) for p in DEFINITION_PREFIXES):
        # disambiguate policy factual
        if any(kw in lower for kw in ["refund", "policy", "handbook", "pricing"]):
            return QuestionType.policy
        return QuestionType.definition
    if lower.startswith(("what is", "what are", "how many", "what does")):
        if any(kw in lower for kw in ["policy", "handbook", "pricing"]):
            return QuestionType.policy
        return QuestionType.factual
    if any(kw in lower for kw in TROUBLESHOOTING_KEYWORDS):
        return QuestionType.troubleshooting
    if lower.startswith(("compare", "difference between", "versus", "vs ")):
        return QuestionType.comparison
    if lower.startswith(("what", "where", "when", "who", "why", "which", "can", "does", "is", "are")):
        return QuestionType.factual
    return QuestionType.unknown


def extract_features(original_query: str, normalized_query: str | None = None) -> QueryFeatures:
    normalized = normalized_query if normalized_query is not None else " ".join(original_query.strip().split())
    # Basic counts
    char_count = len(normalized)
    words = re.findall(r"\b\w+\b", normalized)
    word_count = len(words)
    token_count = max(1, char_count // 4)  # heuristic
    # Signals
    contains_quotes = bool(RE_QUOTES.search(original_query))
    contains_backticks = bool(RE_BACKTICK.search(original_query))
    contains_numbers = bool(RE_NUMBER.search(normalized))
    punctuation_count = len(RE_PUNCT.findall(normalized))
    capitalized_terms = RE_CAPITALIZED.findall(normalized)
    uppercase_terms = RE_UPPER_WORD.findall(normalized)

    # Identifier detection
    snake_matches = RE_SNAKE.findall(normalized)
    camel_matches = RE_CAMEL.findall(normalized)
    upper_matches = RE_UPPER_UNDERSCORE.findall(normalized)
    version_matches = RE_VERSION.findall(normalized)
    # Generic identifier candidates
    identifier_candidates = list(set(snake_matches + camel_matches + upper_matches + version_matches))
    # Also catch any identifier pattern
    if not identifier_candidates:
        identifier_candidates = RE_IDENTIFIER.findall(normalized)
        # filter short false positives (e.g., 'a-b')
        identifier_candidates = [t for t in identifier_candidates if len(t) > 3 and ("_" in t or "-" in t or any(c.isupper() for c in t[1:]))]

    has_snake = bool(snake_matches)
    has_camel = bool(camel_matches)
    has_upper = bool(upper_matches)
    has_version = bool(version_matches)
    contains_identifier = bool(identifier_candidates)

    # Exact phrase: quotes or backticks or strong identifier
    contains_exact_phrase = contains_quotes or contains_backticks or (contains_identifier and word_count <= 6)

    # Special terms heuristic: rare long tokens not in common vocab
    rare_candidates = [w for w in words if len(w) >= 8 and w.lower() not in QUESTION_WORDS]
    # filter common policy words? keep as is for signal
    contains_special_terms = len(rare_candidates) > 0

    # Question word
    contains_question_word = any(w.lower() in QUESTION_WORDS for w in words)
    question_type = detect_question_type(normalized)

    return QueryFeatures(
        original_query=original_query,
        normalized_query=normalized,
        character_count=char_count,
        token_count=token_count,
        word_count=word_count,
        contains_quotes=contains_quotes,
        contains_backticks=contains_backticks,
        contains_numbers=contains_numbers,
        contains_identifier=contains_identifier,
        identifier_candidates=identifier_candidates[:5],
        contains_exact_phrase=contains_exact_phrase,
        contains_special_terms=contains_special_terms,
        contains_question_word=contains_question_word,
        question_type=question_type,
        punctuation_count=punctuation_count,
        capitalized_terms=capitalized_terms[:5],
        uppercase_terms=uppercase_terms[:5],
        rare_term_candidates=rare_candidates[:5],
        has_snake_case=has_snake,
        has_camel_case=has_camel,
        has_upper_case=has_upper,
        has_version_pattern=has_version,
        word_count_raw=word_count,
    )
