import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.document import Document, DocumentStatus, EmbeddingStatus
from app.models.document_chunk import DocumentChunk
from app.models.embedding_job import EmbeddingJob, EmbeddingJobStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_end_to_end_embedding_pipeline(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """
    Verify complete embedding generation flow:
    Upload document ➔ Ingest (READY) ➔ Trigger Embed ➔ Chunks have vectors ➔ Job COMPLETED.
    """
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload Markdown Document
    md_content = b"""# Vector Architecture

RAGForge leverages pgvector in PostgreSQL for efficient vector search and dense similarity.

## Embedding Model

It utilizes BAAI/bge-small-en-v1.5 producing 384-dimensional cosine embeddings.
"""
    upload_res = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("vectors_architecture.md", md_content, "text/markdown")},
    )
    assert upload_res.status_code == status.HTTP_201_CREATED
    doc_id = upload_res.json()["document"]["id"]

    # 2. Ingest Document (Phase 4)
    ingest_res = await client.post(f"/api/v1/documents/{doc_id}/ingest", headers=headers)
    assert ingest_res.status_code == status.HTTP_200_OK

    # 3. Trigger Embedding Generation (Phase 5)
    embed_res = await client.post(f"/api/v1/documents/{doc_id}/embed", headers=headers)
    assert embed_res.status_code == status.HTTP_200_OK
    data = embed_res.json()
    job_id = data["job_id"]
    assert data["status"] == EmbeddingJobStatus.COMPLETED.value
    assert data["processed_chunks"] > 0
    assert data["embedding_model"] == "BAAI/bge-small-en-v1.5"

    # 4. Verify Document Embedding Status
    doc_stmt = select(Document).where(Document.id == doc_id)
    doc = (await db_session.execute(doc_stmt)).scalar_one()
    assert doc.status == DocumentStatus.READY
    assert doc.embedding_status == EmbeddingStatus.COMPLETED

    # 5. Verify EmbeddingJob in DB
    job_stmt = select(EmbeddingJob).where(EmbeddingJob.id == job_id)
    job = (await db_session.execute(job_stmt)).scalar_one()
    assert job.status == EmbeddingJobStatus.COMPLETED
    assert job.processed_chunks == job.total_chunks
    assert job.completed_at is not None
    assert job.embedding_dimension == 384

    # 6. Verify DocumentChunk vectors and metadata in DB
    chunks_stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    chunks = list((await db_session.execute(chunks_stmt)).scalars().all())
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 384
        assert chunk.embedding_model == "BAAI/bge-small-en-v1.5"
        assert chunk.embedding_provider == "local"
        assert chunk.embedding_dimension == 384
        assert chunk.embedded_at is not None

    # 7. Verify API job status endpoint
    job_api_res = await client.get(f"/api/v1/embedding-jobs/{job_id}", headers=headers)
    assert job_api_res.status_code == status.HTTP_200_OK
    assert job_api_res.json()["id"] == job_id
    assert job_api_res.json()["status"] == EmbeddingJobStatus.COMPLETED.value
    assert job_api_res.json()["processed_chunks"] == len(chunks)
