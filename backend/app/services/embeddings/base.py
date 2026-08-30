from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """Abstract protocol for pluggable embedding models and providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the embedding provider (e.g. 'local', 'openai', 'google')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Specific model identifier (e.g. 'BAAI/bge-small-en-v1.5')."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output embedding vector dimension."""
        pass

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Generate dense embeddings for a batch of document/passage chunks.

        Returns:
            list[list[float]]: List of float vectors of fixed dimension.
        """
        pass

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """
        Generate dense embedding for a single search query with model-specific prefix/instructions.

        Returns:
            list[float]: Float vector of fixed dimension.
        """
        pass
