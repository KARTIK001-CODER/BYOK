import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.document_chunk import DocumentChunk
from app.models.embedding_job import EmbeddingJobStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_embedding_idempotency_reuses_existing_vectors(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify that re-triggering embeddings reuses existing vectors without regeneration."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload & Ingest
    content = b"Paragraph 1 text content for idempotency test.\nParagraph 2 text content."
    upload_res = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("idempotency.txt", content, "text/plain")},
    )
    doc_id = upload_res.json()["document"]["id"]
    await client.post(f"/api/v1/documents/{doc_id}/ingest", headers=headers)

    # 2. First Embedding Run
    res1 = await client.post(f"/api/v1/documents/{doc_id}/embed", headers=headers)
    assert res1.status_code == status.HTTP_200_OK
    job_id = res1.json()["job_id"]

    chunks_stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    initial_chunks = list((await db_session.execute(chunks_stmt)).scalars().all())
    initial_vectors = [c.embedding for c in initial_chunks]

    # 3. Second Embedding Run (Idempotency)
    res2 = await client.post(f"/api/v1/documents/{doc_id}/embed", headers=headers)
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["job_id"] == job_id
    assert res2.json()["processed_chunks"] == len(initial_chunks)

    # 4. Verify vectors are identical
    re_chunks = list((await db_session.execute(chunks_stmt)).scalars().all())
    re_vectors = [c.embedding for c in re_chunks]
    assert initial_vectors == re_vectors


@pytest.mark.asyncio
async def test_embed_unprocessed_document_rejected(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify that attempting to embed a document before ingestion (status UPLOADED) is rejected."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Upload document without triggering ingestion
    content = b"Unprocessed document text."
    upload_res = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("unprocessed.txt", content, "text/plain")},
    )
    doc_id = upload_res.json()["document"]["id"]

    # Trigger embed on UPLOADED document -> 422 Unprocessable
    res = await client.post(f"/api/v1/documents/{doc_id}/embed", headers=headers)
    assert res.status_code in [
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        status.HTTP_400_BAD_REQUEST,
    ]
    assert "DOCUMENT_NOT_READY" in res.json().get("error", {}).get("code", "")


@pytest.mark.asyncio
async def test_retry_embedding_job_endpoint(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify retrying a job via POST /api/v1/embedding-jobs/{id}/retry."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Upload & Ingest
    content = b"Sample text for retry test."
    upload_res = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("retry_doc.txt", content, "text/plain")},
    )
    doc_id = upload_res.json()["document"]["id"]
    await client.post(f"/api/v1/documents/{doc_id}/ingest", headers=headers)

    # Initial Embedding
    res = await client.post(f"/api/v1/documents/{doc_id}/embed", headers=headers)
    job_id = res.json()["job_id"]

    # Retry Job
    retry_res = await client.post(f"/api/v1/embedding-jobs/{job_id}/retry", headers=headers)
    assert retry_res.status_code == status.HTTP_200_OK
    assert retry_res.json()["id"] == job_id
    assert retry_res.json()["status"] == EmbeddingJobStatus.COMPLETED.value
