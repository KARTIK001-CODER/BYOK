from dataclasses import dataclass, field

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class ModelCapability:
    streaming: bool = True
    context_window: int = 128000
    max_output_tokens: int = 4096


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    provider: str
    capabilities: ModelCapability = field(default_factory=ModelCapability)
    description: str = ""
    is_default: bool = False


@dataclass
class ProviderInfo:
    id: str
    name: str
    description: str
    is_configured: bool
    default_model: str
    models: list[ModelInfo]


# Canonical registry of supported production LLM models
MODEL_CATALOG: dict[str, list[ModelInfo]] = {
    "groq": [
        ModelInfo(
            id="qwen/qwen3.8-27b",
            name="Qwen 3.8 27B",
            provider="groq",
            capabilities=ModelCapability(
                streaming=True, context_window=128000, max_output_tokens=8192
            ),
            description="High-performance multilingual reasoning and chat model on Groq LPUs.",
            is_default=True,
        ),
        ModelInfo(
            id="groq/compound",
            name="Groq Compound",
            provider="groq",
            capabilities=ModelCapability(
                streaming=True, context_window=128000, max_output_tokens=8192
            ),
            description="Agentic compound reasoning model on ultra-fast Groq infrastructure.",
        ),
        ModelInfo(
            id="groq/compound-mini",
            name="Groq Compound Mini",
            provider="groq",
            capabilities=ModelCapability(
                streaming=True, context_window=128000, max_output_tokens=8192
            ),
            description="Fast lightweight compound reasoning model on Groq.",
        ),
        ModelInfo(
            id="openai/gpt-oss-120b",
            name="GPT OSS 120B",
            provider="groq",
            capabilities=ModelCapability(
                streaming=True, context_window=128000, max_output_tokens=8192
            ),
            description="Large-scale open weight foundation model on Groq.",
        ),
        ModelInfo(
            id="llama-3.3-70b-versatile",
            name="Llama 3.3 70B Versatile",
            provider="groq",
            capabilities=ModelCapability(
                streaming=True, context_window=128000, max_output_tokens=32768
            ),
            description="State-of-the-art open model hosted on ultra-fast Groq LPU infrastructure.",
        ),
        ModelInfo(
            id="llama-3.1-8b-instant",
            name="Llama 3.1 8B Instant",
            provider="groq",
            capabilities=ModelCapability(
                streaming=True, context_window=128000, max_output_tokens=8192
            ),
            description="Ultra-low-latency 8B model for fast conversational QA.",
        ),
        ModelInfo(
            id="mixtral-8x7b-32768",
            name="Mixtral 8x7B",
            provider="groq",
            capabilities=ModelCapability(
                streaming=True, context_window=32768, max_output_tokens=4096
            ),
            description="High-throughput mixture-of-experts model on Groq.",
        ),
    ],
    "openai": [
        ModelInfo(
            id="gpt-4o",
            name="GPT-4o",
            provider="openai",
            capabilities=ModelCapability(
                streaming=True, context_window=128000, max_output_tokens=4096
            ),
            description="Flagship OpenAI multimodal and high-intelligence reasoning model.",
            is_default=True,
        ),
        ModelInfo(
            id="gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openai",
            capabilities=ModelCapability(
                streaming=True, context_window=128000, max_output_tokens=4096
            ),
            description="Fast, cost-efficient, high-accuracy reasoning model.",
        ),
        ModelInfo(
            id="gpt-3.5-turbo",
            name="GPT-3.5 Turbo",
            provider="openai",
            capabilities=ModelCapability(
                streaming=True, context_window=16385, max_output_tokens=4096
            ),
            description="Legacy high-speed generation model.",
        ),
    ],
    "gemini": [
        ModelInfo(
            id="gemini-2.0-flash",
            name="Gemini 2.0 Flash",
            provider="gemini",
            capabilities=ModelCapability(
                streaming=True, context_window=1048576, max_output_tokens=8192
            ),
            description="Next-generation high-speed multimodal model with 1M context window.",
            is_default=True,
        ),
        ModelInfo(
            id="gemini-1.5-flash",
            name="Gemini 1.5 Flash",
            provider="gemini",
            capabilities=ModelCapability(
                streaming=True, context_window=1048576, max_output_tokens=8192
            ),
            description="Fast and versatile multimodal model with 1M token context.",
        ),
        ModelInfo(
            id="gemini-1.5-pro",
            name="Gemini 1.5 Pro",
            provider="gemini",
            capabilities=ModelCapability(
                streaming=True, context_window=2097152, max_output_tokens=8192
            ),
            description="Deep reasoning model with up to 2M token context.",
        ),
    ],
    "mock": [
        ModelInfo(
            id="mock-default",
            name="Mock Test Model",
            provider="mock",
            capabilities=ModelCapability(
                streaming=True, context_window=32768, max_output_tokens=4096
            ),
            description="Deterministic mock provider for automated unit and integration tests.",
            is_default=True,
        ),
    ],
}


class ModelRegistry:
    """Central registry and validator for LLM providers and models."""

    @classmethod
    def get_supported_providers(cls) -> list[str]:
        return list(MODEL_CATALOG.keys())

    @classmethod
    def is_provider_configured(cls, provider: str, settings: Settings | None = None) -> bool:
        cfg = settings or get_settings()
        match provider.lower():
            case "groq":
                return bool(cfg.GROQ_API_KEY and cfg.GROQ_API_KEY.strip())
            case "openai":
                return bool(cfg.OPENAI_API_KEY and cfg.OPENAI_API_KEY.strip())
            case "gemini":
                return bool(cfg.GEMINI_API_KEY and cfg.GEMINI_API_KEY.strip())
            case "mock":
                return True
            case _:
                return False

    @classmethod
    def get_models_for_provider(cls, provider: str) -> list[ModelInfo]:
        return MODEL_CATALOG.get(provider.lower(), [])

    @classmethod
    def get_default_model(cls, provider: str) -> str:
        models = cls.get_models_for_provider(provider)
        for m in models:
            if m.is_default:
                return m.id
        if models:
            return models[0].id
        return ""

    @classmethod
    def is_model_supported(cls, provider: str, model: str) -> bool:
        models = cls.get_models_for_provider(provider)
        return any(m.id == model for m in models)

    @classmethod
    def get_model_info(cls, provider: str, model: str) -> ModelInfo | None:
        models = cls.get_models_for_provider(provider)
        for m in models:
            if m.id == model:
                return m
        return None

    @classmethod
    def list_providers_with_metadata(cls, settings: Settings | None = None) -> list[ProviderInfo]:
        cfg = settings or get_settings()
        result: list[ProviderInfo] = []
        for prov_id, models in MODEL_CATALOG.items():
            if prov_id == "mock" and cfg.APP_ENV != "test":
                continue
            is_cfg = cls.is_provider_configured(prov_id, cfg)
            name_map = {
                "groq": "Groq",
                "openai": "OpenAI",
                "gemini": "Google Gemini",
                "mock": "Mock Provider",
            }
            desc_map = {
                "groq": "Ultra-fast inference via Groq LPU engine.",
                "openai": "OpenAI GPT-4o & GPT models.",
                "gemini": "Google Generative AI multimodal models.",
                "mock": "Mock testing engine.",
            }
            result.append(
                ProviderInfo(
                    id=prov_id,
                    name=name_map.get(prov_id, prov_id.capitalize()),
                    description=desc_map.get(prov_id, ""),
                    is_configured=is_cfg,
                    default_model=cls.get_default_model(prov_id),
                    models=models,
                )
            )
        return result
