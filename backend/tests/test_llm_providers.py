import pytest

from app.services.llm.base import LLMMessage, LLMRequest
from app.services.llm.errors import LLMErrorCode, LLMException
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.gemini import GeminiProvider
from app.services.llm.providers.groq import GroqProvider
from app.services.llm.providers.mock import MockLLMProvider
from app.services.llm.providers.openai import OpenAIProvider
from app.services.llm.registry import ModelRegistry


@pytest.mark.asyncio
async def test_mock_provider_generation():
    """Test MockLLMProvider synchronous generation."""
    provider = MockLLMProvider()
    req = LLMRequest(
        provider="mock",
        model="mock-default",
        messages=[
            LLMMessage(role="system", content="You are an assistant."),
            LLMMessage(role="user", content="How do refresh tokens work?"),
        ],
    )
    resp = await provider.generate(req)
    assert resp.content is not None
    assert "refresh tokens" in resp.content.lower()
    assert resp.provider == "mock"
    assert resp.usage is not None
    assert resp.usage.total_tokens is not None


@pytest.mark.asyncio
async def test_mock_provider_streaming():
    """Test MockLLMProvider token streaming."""
    provider = MockLLMProvider()
    req = LLMRequest(
        provider="mock",
        model="mock-default",
        messages=[LLMMessage(role="user", content="Explain auth tokens.")],
        stream=True,
    )
    chunks = []
    async for chunk in provider.stream(req):
        if chunk.delta:
            chunks.append(chunk.delta)
    assert len(chunks) > 0
    full_text = "".join(chunks)
    assert "tokens" in full_text.lower()


@pytest.mark.asyncio
async def test_mock_provider_simulated_errors():
    """Test error raising in MockLLMProvider."""
    provider = MockLLMProvider(simulate_error=LLMErrorCode.LLM_AUTHENTICATION_FAILED)
    req = LLMRequest(provider="mock", model="mock-default", messages=[])
    with pytest.raises(LLMException) as exc_info:
        await provider.generate(req)
    assert exc_info.value.code == LLMErrorCode.LLM_AUTHENTICATION_FAILED.value
    assert exc_info.value.status_code == 401


def test_model_registry_and_factory():
    """Test registry and factory resolution."""
    # Test registry queries
    providers = ModelRegistry.get_supported_providers()
    assert "groq" in providers
    assert "openai" in providers
    assert "gemini" in providers
    assert "mock" in providers

    assert ModelRegistry.is_model_supported("groq", "llama-3.3-70b-versatile")
    assert ModelRegistry.is_model_supported("openai", "gpt-4o")
    assert not ModelRegistry.is_model_supported("groq", "nonexistent-model-xyz")

    # Test factory instantiation
    inst, model = LLMProviderFactory.create("mock", "mock-default")
    assert isinstance(inst, MockLLMProvider)
    assert model == "mock-default"

    # Unsupported provider
    with pytest.raises(LLMException) as exc_info:
        LLMProviderFactory.create("invalid_provider")
    assert exc_info.value.code == LLMErrorCode.LLM_PROVIDER_UNSUPPORTED.value

    # Unsupported model
    with pytest.raises(LLMException) as exc_info:
        LLMProviderFactory.create("groq", "invalid-model-name")
    assert exc_info.value.code == LLMErrorCode.LLM_MODEL_UNSUPPORTED.value


def test_provider_missing_key_behavior(monkeypatch: pytest.MonkeyPatch):
    """Test that providers without keys raise LLM_PROVIDER_NOT_CONFIGURED."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")

    groq = GroqProvider(api_key=None)
    req = LLMRequest(provider="groq", model="llama-3.3-70b-versatile", messages=[])
    with pytest.raises(LLMException) as exc_info:
        groq._get_api_key(req)
    assert exc_info.value.code == LLMErrorCode.LLM_PROVIDER_NOT_CONFIGURED.value

    openai = OpenAIProvider(api_key=None)
    with pytest.raises(LLMException) as exc_info:
        openai._get_api_key(req)
    assert exc_info.value.code == LLMErrorCode.LLM_PROVIDER_NOT_CONFIGURED.value

    gemini = GeminiProvider(api_key=None)
    with pytest.raises(LLMException) as exc_info:
        gemini._get_api_key(req)
    assert exc_info.value.code == LLMErrorCode.LLM_PROVIDER_NOT_CONFIGURED.value
