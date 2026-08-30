import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_end_to_end_markdown_ingestion_pipeline(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify full ingestion pipeline: upload MD -> trigger ingest -> chunks persisted -> READY."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload Markdown Document
    md_content = b"""# RAGForge Engine

RAGForge is a production-oriented RAG platform designed for enterprise workloads.

## Architecture

It uses FastAPI, PostgreSQL with pgvector, and custom modular extractors.

## Ingestion Pipeline

Documents are parsed, normalized, and recursively chunked with provenance metadata.
"""
    upload_res = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("ragforge_manual.md", md_content, "text/markdown")},
    )
    assert upload_res.status_code == status.HTTP_201_CREATED
    doc_id = upload_res.json()["document"]["id"]

    # 2. Trigger Ingestion
    ingest_res = await client.post(f"/api/v1/documents/{doc_id}/ingest", headers=headers)
    assert ingest_res.status_code == status.HTTP_200_OK
    data = ingest_res.json()
    job_id = data["job_id"]
    assert data["status"] == IngestionJobStatus.COMPLETED.value

    # 3. Verify Document is marked READY
    doc_stmt = select(Document).where(Document.id == doc_id)
    doc = (await db_session.execute(doc_stmt)).scalar_one()
    assert doc.status == DocumentStatus.READY

    # 4. Verify IngestionJob record
    job_stmt = select(IngestionJob).where(IngestionJob.id == job_id)
    job = (await db_session.execute(job_stmt)).scalar_one()
    assert job.status == IngestionJobStatus.COMPLETED
    assert job.completed_at is not None
    assert job.attempt_count == 1

    # 5. Verify Chunks in DB
    chunks_stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    chunks = list((await db_session.execute(chunks_stmt)).scalars().all())
    assert len(chunks) >= 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].organization_id == test_kb.organization_id
    assert chunks[0].knowledge_base_id == test_kb.id

    # 6. Verify API chunk listing endpoint
    chunks_res = await client.get(f"/api/v1/documents/{doc_id}/chunks", headers=headers)
    assert chunks_res.status_code == status.HTTP_200_OK
    assert chunks_res.json()["total"] == len(chunks)

    # 7. Verify API job status endpoint
    job_api_res = await client.get(f"/api/v1/ingestion-jobs/{job_id}", headers=headers)
    assert job_api_res.status_code == status.HTTP_200_OK
    assert job_api_res.json()["id"] == job_id
    assert job_api_res.json()["status"] == IngestionJobStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_ingestion_idempotency_and_reprocessing(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify triggering ingestion multiple times does not produce duplicate chunks."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload Plain Text Document
    txt_content = b"Line 1 text content.\nLine 2 text content.\nLine 3 text content."
    upload_res = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("reprocess.txt", txt_content, "text/plain")},
    )
    doc_id = upload_res.json()["document"]["id"]

    # 2. First Ingestion
    res1 = await client.post(f"/api/v1/documents/{doc_id}/ingest", headers=headers)
    assert res1.status_code == status.HTTP_200_OK
    job_id = res1.json()["job_id"]

    count_stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    initial_chunk_count = len(list((await db_session.execute(count_stmt)).scalars().all()))
    assert initial_chunk_count > 0

    # 3. Second Ingestion (Reprocessing)
    res2 = await client.post(f"/api/v1/documents/{doc_id}/ingest", headers=headers)
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["job_id"] == job_id

    # 4. Verify chunk count is IDENTICAL (no duplicates created)
    reprocessed_chunks = list((await db_session.execute(count_stmt)).scalars().all())
    assert len(reprocessed_chunks) == initial_chunk_count

    # Verify attempt_count was incremented to 2
    job_stmt = select(IngestionJob).where(IngestionJob.id == job_id)
    job = (await db_session.execute(job_stmt)).scalar_one()
    assert job.attempt_count == 2
