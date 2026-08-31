import logging

from app.core.config import get_settings
from app.services.llm.base import LLMProvider, ProviderCredentials
from app.services.llm.errors import LLMErrorCode, LLMException
from app.services.llm.providers.gemini import GeminiProvider
from app.services.llm.providers.groq import GroqProvider
from app.services.llm.providers.mock import MockLLMProvider
from app.services.llm.providers.openai import OpenAIProvider
from app.services.llm.registry import ModelRegistry

logger = logging.getLogger("app.services.llm.factory")


class LLMProviderFactory:
    """Factory for resolving and instantiating configured LLM providers and models."""

    _mock_instance: MockLLMProvider | None = None

    @classmethod
    def set_mock_provider(cls, mock_provider: MockLLMProvider | None) -> None:
        """Inject a mock provider override for test execution."""
        cls._mock_instance = mock_provider

    @classmethod
    def create(
        cls,
        provider: str | None = None,
        model: str | None = None,
        credentials: ProviderCredentials | None = None,
    ) -> tuple[LLMProvider, str]:
        """
        Instantiate an LLM provider and resolve validated model name.

        Args:
            provider: Provider name ('groq', 'openai', 'gemini', 'mock').
            model: Model identifier string.
            credentials: BYOK or custom credentials override if provided.

        Returns:
            tuple[LLMProvider, str]: (provider_instance, resolved_model_name)
        """
        settings = get_settings()
        selected_provider = (provider or settings.DEFAULT_LLM_PROVIDER).strip().lower()

        # Validate provider support
        if selected_provider not in ModelRegistry.get_supported_providers():
            raise LLMException(
                message=f"Unsupported LLM provider: '{selected_provider}'. Supported: {ModelRegistry.get_supported_providers()}",
                code=LLMErrorCode.LLM_PROVIDER_UNSUPPORTED,
                status_code=400,
            )

        # Resolve and validate model
        resolved_model = model.strip() if model and model.strip() else None
        if not resolved_model:
            if selected_provider == settings.DEFAULT_LLM_PROVIDER and settings.DEFAULT_LLM_MODEL:
                resolved_model = settings.DEFAULT_LLM_MODEL
            else:
                resolved_model = ModelRegistry.get_default_model(selected_provider)

        if not resolved_model:
            raise LLMException(
                message=f"No default model configured for provider: '{selected_provider}'.",
                code=LLMErrorCode.LLM_MODEL_UNSUPPORTED,
                status_code=400,
            )

        if (
            not ModelRegistry.is_model_supported(selected_provider, resolved_model)
            and selected_provider != "mock"
        ):
            valid_models = [m.id for m in ModelRegistry.get_models_for_provider(selected_provider)]
            raise LLMException(
                message=f"Unsupported model '{resolved_model}' for provider '{selected_provider}'. Valid models: {valid_models}",
                code=LLMErrorCode.LLM_MODEL_UNSUPPORTED,
                status_code=400,
            )

        api_key = credentials.api_key if credentials else None

        # Instantiate provider
        match selected_provider:
            case "groq":
                inst = GroqProvider(api_key=api_key)
            case "openai":
                inst = OpenAIProvider(api_key=api_key)
            case "gemini":
                inst = GeminiProvider(api_key=api_key)
            case "mock":
                inst = cls._mock_instance or MockLLMProvider()
            case _:
                raise LLMException(
                    message=f"Provider factory cannot instantiate '{selected_provider}'.",
                    code=LLMErrorCode.LLM_PROVIDER_UNSUPPORTED,
                    status_code=400,
                )

        return inst, resolved_model
