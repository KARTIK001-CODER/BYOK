import logging
from dataclasses import dataclass
from typing import Any

from app.services.rag.citations import CitationBuilder
from app.services.retrieval.schemas import RetrievalResult

logger = logging.getLogger("app.evaluation.generation")


@dataclass
class GroundingTestCase:
    id: str
    question: str
    expected_points: list[str]
    should_have_answer: bool
    context_chunks: list[dict[str, Any]]


@dataclass
class EvaluationReport:
    total_cases: int
    grounding_passed: int
    citation_validity_passed: int
    no_answer_passed: int
    details: list[dict[str, Any]]


class GenerationEvaluator:
    """Evaluates RAG groundedness, citation validity, and no-answer threshold behavior."""

    @staticmethod
    def evaluate_citations(
        answer: str,
        retrieved_chunks: list[RetrievalResult],
    ) -> bool:
        """Verify that every citation ID output in answer exists in the retrieved context."""
        builder = CitationBuilder()
        referenced_ids = builder.extract_citation_ids(answer)
        if not referenced_ids:
            return True
        max_valid_id = len(retrieved_chunks)
        return all(1 <= cid <= max_valid_id for cid in referenced_ids)

    @classmethod
    def evaluate_case(
        cls,
        case: GroundingTestCase,
        answer: str,
        retrieved_chunks: list[RetrievalResult],
    ) -> dict[str, Any]:
        """Evaluate a single test case response against golden expectations."""
        citations_valid = cls.evaluate_citations(answer, retrieved_chunks)

        if not case.should_have_answer:
            no_answer_correct = (
                "couldn't find enough information" in answer.lower()
                or "not available" in answer.lower()
                or "no relevant" in answer.lower()
            )
            return {
                "case_id": case.id,
                "grounding_passed": no_answer_correct,
                "citations_valid": citations_valid,
                "no_answer_passed": no_answer_correct,
            }

        # Check expected points
        lower_answer = answer.lower()
        matched_points = [pt for pt in case.expected_points if pt.lower() in lower_answer]
        grounding_passed = len(matched_points) >= max(1, len(case.expected_points) // 2)

        return {
            "case_id": case.id,
            "grounding_passed": grounding_passed,
            "citations_valid": citations_valid,
            "no_answer_passed": True,
            "matched_points": matched_points,
            "total_expected_points": len(case.expected_points),
        }
