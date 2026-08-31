from collections.abc import AsyncGenerator, Callable

from app.services.llm.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    TokenUsage,
)
from app.services.llm.errors import LLMErrorCode, LLMException


class MockLLMProvider(LLMProvider):
    """Deterministic Mock LLM Provider for unit, integration, and offline evaluation tests."""

    def __init__(
        self,
        default_response: str | None = None,
        custom_responder: Callable[[LLMRequest], str] | None = None,
        simulate_error: LLMErrorCode | None = None,
    ) -> None:
        self._default_response = default_response or (
            "Based on the provided knowledge base, the system uses JWT access tokens for API requests "
            "and rotating refresh tokens for session prolongation. [1] "
            "Tokens are automatically revoked upon logout or rotation anomaly. [2]"
        )
        self._custom_responder = custom_responder
        self._simulate_error = simulate_error

    @property
    def name(self) -> str:
        return "mock"

    def set_response(self, response: str) -> None:
        self._default_response = response

    def set_error(self, error: LLMErrorCode | None) -> None:
        self._simulate_error = error

    def _generate_text(self, request: LLMRequest) -> str:
        if self._simulate_error:
            match self._simulate_error:
                case LLMErrorCode.LLM_AUTHENTICATION_FAILED:
                    raise LLMException(
                        message="Mock authentication failed.",
                        code=LLMErrorCode.LLM_AUTHENTICATION_FAILED,
                        status_code=401,
                    )
                case LLMErrorCode.LLM_RATE_LIMITED:
                    raise LLMException(
                        message="Mock rate limited.",
                        code=LLMErrorCode.LLM_RATE_LIMITED,
                        status_code=429,
                    )
                case LLMErrorCode.LLM_TIMEOUT:
                    raise LLMException(
                        message="Mock request timed out.",
                        code=LLMErrorCode.LLM_TIMEOUT,
                        status_code=504,
                    )
                case _:
                    raise LLMException(
                        message="Mock generation failed.",
                        code=self._simulate_error,
                        status_code=500,
                    )

        if self._custom_responder:
            return self._custom_responder(request)

        # Check if context is completely empty / insufficient
        user_or_context = " ".join(m.content for m in request.messages)
        if (
            "NO RELEVANT KNOWLEDGE BASE CONTEXT AVAILABLE" in user_or_context
            or "No relevant documents found" in user_or_context
        ):
            return "I couldn't find enough information in the selected knowledge base to answer that confidently."

        return self._default_response

    async def generate(self, request: LLMRequest) -> LLMResponse:
        content = self._generate_text(request)
        prompt_chars = sum(len(m.content) for m in request.messages)
        usage = TokenUsage(
            prompt_tokens=max(1, prompt_chars // 4),
            completion_tokens=max(1, len(content) // 4),
            total_tokens=max(2, (prompt_chars + len(content)) // 4),
        )
        return LLMResponse(
            content=content,
            model=request.model or "mock-default",
            provider="mock",
            finish_reason="stop",
            usage=usage,
            latency_ms=10.0,
        )

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMStreamChunk, None]:
        content = self._generate_text(request)
        prompt_chars = sum(len(m.content) for m in request.messages)
        usage = TokenUsage(
            prompt_tokens=max(1, prompt_chars // 4),
            completion_tokens=max(1, len(content) // 4),
            total_tokens=max(2, (prompt_chars + len(content)) // 4),
        )

        words = content.split(" ")
        for idx, word in enumerate(words):
            suffix = " " if idx < len(words) - 1 else ""
            chunk_delta = word + suffix
            is_last = idx == len(words) - 1
            yield LLMStreamChunk(
                delta=chunk_delta,
                finish_reason="stop" if is_last else None,
                usage=usage if is_last else None,
            )
