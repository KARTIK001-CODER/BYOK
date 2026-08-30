import pytest

from app.services.embeddings.errors import EmbeddingErrorCode, EmbeddingException
from app.services.embeddings.providers.local import LocalEmbeddingProvider


def test_local_embedding_provider_initialization() -> None:
    """Verify LocalEmbeddingProvider initializes and exposes correct metadata."""
    provider = LocalEmbeddingProvider()
    assert provider.provider_name == "local"
    assert provider.dimension == 384
    assert "bge" in provider.model_name.lower() or "minilm" in provider.model_name.lower()


def test_local_embedding_provider_embed_documents() -> None:
    """Verify batch document embedding generation and dimension correctness."""
    provider = LocalEmbeddingProvider()
    texts = [
        "RAGForge is a production-oriented RAG system.",
        "PostgreSQL and pgvector provide hybrid vector search capabilities.",
        "FastAPI handles async HTTP requests efficiently.",
    ]
    vectors = provider.embed_documents(texts)

    assert len(vectors) == len(texts)
    for vec in vectors:
        assert len(vec) == 384
        assert all(isinstance(val, float) for val in vec)
        # Verify vector is not all zeros
        assert any(val != 0.0 for val in vec)


def test_local_embedding_provider_embed_query() -> None:
    """Verify query embedding generation with query prefix instruction."""
    provider = LocalEmbeddingProvider()
    query = "How does vector search work in PostgreSQL?"
    vec = provider.embed_query(query)

    assert len(vec) == 384
    assert all(isinstance(val, float) for val in vec)


def test_local_embedding_provider_empty_rejected() -> None:
    """Verify embedding empty texts raises EmbeddingException."""
    provider = LocalEmbeddingProvider()

    with pytest.raises(EmbeddingException) as exc_info:
        provider.embed_documents(["   "])
    assert exc_info.value.code == EmbeddingErrorCode.EMPTY_CHUNK.value

    with pytest.raises(EmbeddingException) as query_exc:
        provider.embed_query("  \t \n ")
    assert query_exc.value.code == EmbeddingErrorCode.EMPTY_CHUNK.value


def test_local_embedding_provider_unicode() -> None:
    """Verify multilingual and Unicode text embeddings."""
    provider = LocalEmbeddingProvider()
    unicode_texts = [
        "Intelligence artificielle et bases de données vectorielles.",
        "人工智能和向量数据库.",
        "Búsqueda semántica de alto rendimiento.",
    ]
    vectors = provider.embed_documents(unicode_texts)
    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 384
