import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.generation import GenerationEvaluator, GroundingTestCase
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService


@pytest.mark.asyncio
async def test_rag_service_no_context_behavior(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Test grounded no-answer behavior when no relevant documents exist in KB."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="What is the internal database password?",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    resp = await rag_service.generate(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        request=req,
    )

    assert resp.conversation_id is not None
    assert resp.retrieval.result_count == 0
    assert "couldn't find enough information" in resp.answer.lower()
    assert len(resp.citations) == 0


def test_generation_evaluator():
    """Test the GenerationEvaluator helper on positive and negative cases."""
    case_pos = GroundingTestCase(
        id="case-1",
        question="What is token rotation?",
        expected_points=["rotated", "single use"],
        should_have_answer=True,
        context_chunks=[],
    )
    ans_pos = "Refresh tokens are rotated after single use. [1]"
    res_pos = GenerationEvaluator.evaluate_case(case_pos, ans_pos, [])
    assert res_pos["grounding_passed"] is True

    case_neg = GroundingTestCase(
        id="case-2",
        question="What is the CEO's favorite food?",
        expected_points=[],
        should_have_answer=False,
        context_chunks=[],
    )
    ans_neg = "I couldn't find enough information in the selected knowledge base to answer that confidently."
    res_neg = GenerationEvaluator.evaluate_case(case_neg, ans_neg, [])
    assert res_neg["no_answer_passed"] is True
