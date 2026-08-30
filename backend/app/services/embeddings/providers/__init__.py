from app.core.config import get_settings
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.errors import EmbeddingErrorCode, EmbeddingException
from app.services.embeddings.providers.local import LocalEmbeddingProvider


def get_embedding_provider(provider_type: str | None = None) -> BaseEmbeddingProvider:
    """Factory returning configured embedding provider instance."""
    settings = get_settings()
    p_type = provider_type or settings.EMBEDDING_PROVIDER

    if p_type == "local":
        return LocalEmbeddingProvider(
            model_name=settings.EMBEDDING_MODEL,
            dimension=settings.EMBEDDING_DIMENSION,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
        )
    else:
        raise EmbeddingException(
            message=f"Unsupported embedding provider '{p_type}'. Supported: 'local'",
            code=EmbeddingErrorCode.EMBEDDING_PROVIDER_FAILED,
        )


__all__ = [
    "BaseEmbeddingProvider",
    "LocalEmbeddingProvider",
    "get_embedding_provider",
]
