from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMMessage:
    """A single message in the LLM conversation context."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class TokenUsage:
    """Captured or estimated token consumption for a generation request."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class ProviderCredentials:
    """Container for API keys and server/user credential abstraction for BYOK readiness."""

    api_key: str | None = None
    api_base: str | None = None
    organization: str | None = None
    source: str = "server"  # "server" or "user"


@dataclass
class LLMRequest:
    """Normalized generation request passed to providers."""

    provider: str
    model: str
    messages: list[LLMMessage]
    temperature: float = 0.2
    max_tokens: int = 4096
    stream: bool = False
    credentials: ProviderCredentials | None = None
    request_id: str | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Normalized generation response returned from providers."""

    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    latency_ms: float = 0.0


@dataclass
class LLMStreamChunk:
    """A streaming delta chunk yielded during token streaming."""

    delta: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol interface that all LLM provider implementations must satisfy."""

    @property
    def name(self) -> str:
        """Provider identifier string (e.g. 'groq', 'openai', 'gemini', 'mock')."""
        ...

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute non-streaming text generation."""
        ...

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMStreamChunk, None]:
        """Execute streaming text generation yielding delta chunks."""
        ...
