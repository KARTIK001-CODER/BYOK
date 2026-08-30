import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundException
from app.models.document import Document, DocumentStatus, EmbeddingStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.embedding_job import EmbeddingJob, EmbeddingJobStatus
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.errors import EmbeddingErrorCode, EmbeddingException
from app.services.embeddings.providers import get_embedding_provider

logger = logging.getLogger("app.services.embeddings")


class EmbeddingService:
    """Service orchestrating batch vector embedding generation and pgvector persistence."""

    @staticmethod
    async def process_document_embeddings(
        session: AsyncSession,
        document: Document,
        provider: BaseEmbeddingProvider | None = None,
    ) -> EmbeddingJob:
        """
        Generate and persist vector embeddings for all chunks belonging to a READY document.
        Guarantees batch resumability and model-aware idempotency.
        """
        settings = get_settings()
        embedding_provider = provider or get_embedding_provider()
        start_time = time.perf_counter()

        # 1. Verify Document is in READY processing state
        if document.status != DocumentStatus.READY:
            msg = (
                f"Document must be in READY state before embedding "
                f"(current: {document.status.value})."
            )
            raise EmbeddingException(
                message=msg,
                code=EmbeddingErrorCode.DOCUMENT_NOT_READY,
            )

        # 2. Fetch active document version
        version_stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version_number == document.current_version,
        )
        version_res = await session.execute(version_stmt)
        doc_version = version_res.scalar_one_or_none()
        if doc_version is None:
            raise NotFoundException(message="Document version not found.")

        # 3. Fetch all chunks for this document version
        chunks_stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == doc_version.id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        chunks_res = await session.execute(chunks_stmt)
        chunks = list(chunks_res.scalars().all())

        if not chunks:
            raise EmbeddingException(
                message="No chunks found for document. Process document before embedding.",
                code=EmbeddingErrorCode.NO_CHUNKS_FOUND,
            )

        if len(chunks) > settings.MAX_EMBEDDING_CHUNKS_PER_JOB:
            raise EmbeddingException(
                message=(
                    f"Document has {len(chunks)} chunks, exceeding max "
                    f"limit of {settings.MAX_EMBEDDING_CHUNKS_PER_JOB}."
                ),
                code=EmbeddingErrorCode.TOO_MANY_CHUNKS,
            )

        # 4. Check for existing EmbeddingJob or create a new one
        job_stmt = select(EmbeddingJob).where(EmbeddingJob.document_version_id == doc_version.id)
        existing_job = (await session.execute(job_stmt)).scalar_one_or_none()

        now = datetime.now(UTC)
        if existing_job is None:
            job = EmbeddingJob(
                id=str(uuid.uuid4()),
                document_id=document.id,
                document_version_id=doc_version.id,
                organization_id=document.organization_id,
                status=EmbeddingJobStatus.PROCESSING,
                attempt_count=1,
                total_chunks=len(chunks),
                processed_chunks=0,
                failed_chunks=0,
                embedding_model=embedding_provider.model_name,
                embedding_dimension=embedding_provider.dimension,
                started_at=now,
            )
            session.add(job)
        else:
            job = existing_job
            job.status = EmbeddingJobStatus.PROCESSING
            job.attempt_count += 1
            job.total_chunks = len(chunks)
            job.embedding_model = embedding_provider.model_name
            job.embedding_dimension = embedding_provider.dimension
            job.started_at = now
            job.failed_at = None
            job.error_code = None
            job.error_message = None

        document.embedding_status = EmbeddingStatus.PROCESSING
        await session.commit()
        await session.refresh(job)
        await session.refresh(document)

        logger.info(
            "Starting embedding job id=%s for doc_id=%s (model=%s, chunks=%d)",
            job.id,
            document.id,
            job.embedding_model,
            len(chunks),
        )

        try:
            # 5. Filter un-embedded chunks (model-aware idempotency)
            unembedded_chunks = [
                c
                for c in chunks
                if c.embedding is None or c.embedding_model != embedding_provider.model_name
            ]
            already_embedded_count = len(chunks) - len(unembedded_chunks)
            job.processed_chunks = already_embedded_count

            # 6. Process in batches
            batch_size = settings.EMBEDDING_BATCH_SIZE
            for i in range(0, len(unembedded_chunks), batch_size):
                batch = unembedded_chunks[i : i + batch_size]
                texts = [c.content for c in batch]

                # Generate embeddings for batch
                vectors = embedding_provider.embed_documents(texts)

                # Persist vectors to chunks
                for chunk, vector in zip(batch, vectors, strict=True):
                    chunk.embedding = vector
                    chunk.embedding_model = embedding_provider.model_name
                    chunk.embedding_provider = embedding_provider.provider_name
                    chunk.embedding_dimension = embedding_provider.dimension
                    chunk.embedded_at = datetime.now(UTC)

                job.processed_chunks += len(batch)
                await session.commit()
                logger.debug(
                    "Embedded batch %d/%d chunks for job id=%s",
                    job.processed_chunks,
                    job.total_chunks,
                    job.id,
                )

            # 7. Finalize Job
            job.status = EmbeddingJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            document.embedding_status = EmbeddingStatus.COMPLETED

            await session.commit()
            await session.refresh(job)
            await session.refresh(document)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info(
                "Embedding job completed id=%s for doc_id=%s (%d chunks in %.2f ms)",
                job.id,
                document.id,
                job.total_chunks,
                duration_ms,
            )
            return job

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_code = (
                exc.code
                if isinstance(exc, EmbeddingException)
                else EmbeddingErrorCode.INTERNAL_ERROR.value
            )
            error_msg = str(exc)

            logger.error(
                "Embedding job failed id=%s for doc_id=%s: [%s] %s (%.2f ms)",
                job.id,
                document.id,
                error_code,
                error_msg,
                duration_ms,
            )

            job.status = EmbeddingJobStatus.FAILED
            job.failed_at = datetime.now(UTC)
            job.error_code = error_code
            job.error_message = error_msg
            document.embedding_status = EmbeddingStatus.FAILED

            await session.commit()
            await session.refresh(job)
            await session.refresh(document)

            if isinstance(exc, EmbeddingException):
                raise exc
            raise EmbeddingException(
                message=f"Embedding pipeline execution failed: {error_msg}",
                code=EmbeddingErrorCode.INTERNAL_ERROR,
            ) from exc

    @staticmethod
    async def get_job_by_id(
        session: AsyncSession,
        job_id: str,
        organization_id: str | None = None,
    ) -> EmbeddingJob:
        """Retrieve an EmbeddingJob by ID with optional tenant scoping."""
        stmt = select(EmbeddingJob).where(EmbeddingJob.id == job_id)
        if organization_id:
            stmt = stmt.where(EmbeddingJob.organization_id == organization_id)

        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundException(message="Embedding job not found.")
        return job

    @staticmethod
    async def retry_job(
        session: AsyncSession,
        job_id: str,
        organization_id: str,
    ) -> EmbeddingJob:
        """Retry a failed embedding job for a document."""
        job = await EmbeddingService.get_job_by_id(session, job_id, organization_id)
        doc_stmt = select(Document).where(Document.id == job.document_id)
        document = (await session.execute(doc_stmt)).scalar_one_or_none()
        if document is None:
            raise NotFoundException(message="Target document not found.")

        return await EmbeddingService.process_document_embeddings(
            session=session,
            document=document,
        )
