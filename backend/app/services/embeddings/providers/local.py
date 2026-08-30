import logging

from fastembed import TextEmbedding

from app.core.config import get_settings
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.errors import EmbeddingErrorCode, EmbeddingException

logger = logging.getLogger("app.services.embeddings.providers.local")

# Cached model instance singleton across requests
_GLOBAL_LOCAL_EMBEDDING_MODEL: TextEmbedding | None = None


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """
    Local, CPU-optimized embedding provider using fastembed ONNX runtime.
    Default model: BAAI/bge-small-en-v1.5 (dimension: 384, cosine similarity).
    """

    DEFAULT_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(
        self,
        model_name: str | None = None,
        dimension: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.EMBEDDING_MODEL
        self._dimension = dimension or settings.EMBEDDING_DIMENSION
        self._batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self._model = self._get_or_load_model()

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_or_load_model(self) -> TextEmbedding:
        """Load or retrieve the cached singleton fastembed model."""
        global _GLOBAL_LOCAL_EMBEDDING_MODEL
        if _GLOBAL_LOCAL_EMBEDDING_MODEL is None:
            logger.info("Initializing LocalEmbeddingProvider model: %s", self._model_name)
            try:
                _GLOBAL_LOCAL_EMBEDDING_MODEL = TextEmbedding(
                    model_name=self._model_name,
                    batch_size=self._batch_size,
                )
                logger.info("Model %s loaded successfully.", self._model_name)
            except Exception as exc:
                logger.error("Failed to load local embedding model: %s", str(exc))
                raise EmbeddingException(
                    message=f"Failed to load embedding model '{self._model_name}': {exc!s}",
                    code=EmbeddingErrorCode.MODEL_LOAD_FAILED,
                ) from exc
        return _GLOBAL_LOCAL_EMBEDDING_MODEL

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized vector embeddings for a list of document passages."""
        if not texts:
            return []

        # Validate non-empty texts
        cleaned_texts = [t.strip() if t else "" for t in texts]
        if any(not t for t in cleaned_texts):
            raise EmbeddingException(
                message="Cannot embed empty text chunks.",
                code=EmbeddingErrorCode.EMPTY_CHUNK,
            )

        try:
            generator = self._model.embed(cleaned_texts, batch_size=self._batch_size)
            vectors: list[list[float]] = []

            for vec in generator:
                vec_list = [float(v) for v in vec]
                # Validate output dimension
                if len(vec_list) != self._dimension:
                    raise EmbeddingException(
                        message=(
                            f"Model produced vector of dimension {len(vec_list)}, "
                            f"expected {self._dimension}."
                        ),
                        code=EmbeddingErrorCode.EMBEDDING_DIMENSION_MISMATCH,
                    )
                vectors.append(vec_list)

            return vectors
        except EmbeddingException:
            raise
        except Exception as exc:
            logger.error("Document embedding generation failed: %s", str(exc))
            raise EmbeddingException(
                message=f"Embedding provider generation failed: {exc!s}",
                code=EmbeddingErrorCode.EMBEDDING_PROVIDER_FAILED,
            ) from exc

    def embed_query(self, query: str) -> list[float]:
        """Generate normalized vector embedding for a single retrieval query."""
        cleaned_query = query.strip() if query else ""
        if not cleaned_query:
            raise EmbeddingException(
                message="Query text cannot be empty.",
                code=EmbeddingErrorCode.EMPTY_CHUNK,
            )

        # Apply BGE query instruction prefix if appropriate
        prefixed_query = (
            f"{self.DEFAULT_QUERY_PREFIX}{cleaned_query}"
            if "bge" in self._model_name.lower()
            else cleaned_query
        )

        try:
            generator = self._model.embed([prefixed_query], batch_size=1)
            raw_vec = next(generator)
            vec_list = [float(v) for v in raw_vec]

            if len(vec_list) != self._dimension:
                raise EmbeddingException(
                    message=(
                        f"Model produced query vector of dimension {len(vec_list)}, "
                        f"expected {self._dimension}."
                    ),
                    code=EmbeddingErrorCode.EMBEDDING_DIMENSION_MISMATCH,
                )
            return vec_list
        except EmbeddingException:
            raise
        except Exception as exc:
            logger.error("Query embedding generation failed: %s", str(exc))
            raise EmbeddingException(
                message=f"Query embedding generation failed: {exc!s}",
                code=EmbeddingErrorCode.EMBEDDING_PROVIDER_FAILED,
            ) from exc
