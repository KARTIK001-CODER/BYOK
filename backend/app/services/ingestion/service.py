import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundException
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.services.documents.storage import StorageService, get_storage_service
from app.services.ingestion.chunking.recursive import RecursiveTextChunker
from app.services.ingestion.errors import IngestionErrorCode, IngestionException
from app.services.ingestion.extractors import get_extractor_for_file

logger = logging.getLogger("app.services.ingestion")


class IngestionService:
    """Service orchestrating document extraction, normalization, chunking, and persistence."""

    @staticmethod
    async def process_document(
        session: AsyncSession,
        document: Document,
        storage: StorageService | None = None,
    ) -> IngestionJob:
        """
        Execute the full ingestion pipeline for a document's latest version.
        Guarantees idempotency and safe retry tracking.
        """
        settings = get_settings()
        storage_service = storage or get_storage_service()
        start_time = time.perf_counter()

        # 1. Fetch latest document version
        version_stmt = (
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version_number == document.current_version,
            )
            .order_by(DocumentVersion.version_number.desc())
        )
        version_res = await session.execute(version_stmt)
        doc_version = version_res.scalar_one_or_none()
        if doc_version is None:
            raise NotFoundException(message="Document version record not found.")

        # 2. Check for existing IngestionJob or create a new one
        existing_job_stmt = select(IngestionJob).where(
            IngestionJob.document_version_id == doc_version.id
        )
        job_res = await session.execute(existing_job_stmt)
        job = job_res.scalar_one_or_none()

        now = datetime.now(UTC)
        if job is None:
            job = IngestionJob(
                id=str(uuid.uuid4()),
                document_id=document.id,
                document_version_id=doc_version.id,
                organization_id=document.organization_id,
                status=IngestionJobStatus.PROCESSING,
                attempt_count=1,
                started_at=now,
            )
            session.add(job)
        else:
            job.status = IngestionJobStatus.PROCESSING
            job.attempt_count += 1
            job.started_at = now
            job.failed_at = None
            job.error_code = None
            job.error_message = None

        document.status = DocumentStatus.PROCESSING
        await session.commit()
        await session.refresh(job)
        await session.refresh(document)

        logger.info(
            "Starting ingestion job id=%s for doc_id=%s (attempt=%d)",
            job.id,
            document.id,
            job.attempt_count,
        )

        try:
            # 3. Read binary file from Storage
            try:
                content = await storage_service.download_file(doc_version.storage_key)
            except Exception as read_exc:
                raise IngestionException(
                    message=f"Storage read failed: {read_exc!s}",
                    code=IngestionErrorCode.STORAGE_READ_FAILED,
                ) from read_exc

            # 4. Extract sections
            extractor = get_extractor_for_file(
                filename=document.original_filename,
                content_type=document.content_type,
            )
            sections = extractor.extract(content)
            if not sections:
                raise IngestionException(
                    message="Document yielded no text sections.",
                    code=IngestionErrorCode.EMPTY_DOCUMENT,
                )

            # 5. Check text length safeguard
            total_chars = sum(len(s.text) for s in sections)
            if total_chars > settings.MAX_EXTRACTED_TEXT_CHARS:
                msg = (
                    f"Extracted text ({total_chars} chars) exceeds "
                    f"limit of {settings.MAX_EXTRACTED_TEXT_CHARS} chars."
                )
                raise IngestionException(
                    message=msg,
                    code=IngestionErrorCode.RESOURCE_LIMIT_EXCEEDED,
                )

            # 6. Chunk sections
            chunker = RecursiveTextChunker(
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
            )
            raw_chunks = chunker.chunk(sections)
            if not raw_chunks:
                raise IngestionException(
                    message="Chunking produced 0 chunks.",
                    code=IngestionErrorCode.CHUNKING_FAILED,
                )

            if len(raw_chunks) > settings.MAX_CHUNKS_PER_DOCUMENT:
                msg = (
                    f"Document produced {len(raw_chunks)} chunks, "
                    f"exceeding max of {settings.MAX_CHUNKS_PER_DOCUMENT}."
                )
                raise IngestionException(
                    message=msg,
                    code=IngestionErrorCode.RESOURCE_LIMIT_EXCEEDED,
                )

            # 7. Atomic Persistence
            # Delete previous chunks for this version (Idempotency)
            del_stmt = delete(DocumentChunk).where(
                DocumentChunk.document_version_id == doc_version.id
            )
            await session.execute(del_stmt)

            # Insert new DocumentChunk records
            chunk_records: list[DocumentChunk] = []
            for idx, rc in enumerate(raw_chunks):
                chunk_record = DocumentChunk(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    document_version_id=doc_version.id,
                    organization_id=document.organization_id,
                    knowledge_base_id=document.knowledge_base_id,
                    chunk_index=idx,
                    content=rc.content,
                    character_count=rc.character_count,
                    word_count=rc.word_count,
                    page_number=rc.page_number,
                    section_title=rc.section_title,
                    chunk_metadata={
                        "document_name": document.name,
                        "content_type": document.content_type,
                        "version_number": doc_version.version_number,
                    },
                )
                chunk_records.append(chunk_record)

            session.add_all(chunk_records)

            # Update Document & Job Status
            job.status = IngestionJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            document.status = DocumentStatus.READY

            await session.commit()
            await session.refresh(job)
            await session.refresh(document)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info(
                "Ingestion completed for doc_id=%s. Created %d chunks in %.2f ms",
                document.id,
                len(chunk_records),
                duration_ms,
            )
            return job

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_code = (
                exc.code
                if isinstance(exc, IngestionException)
                else IngestionErrorCode.INTERNAL_ERROR.value
            )
            error_msg = str(exc)

            logger.error(
                "Ingestion failed for doc_id=%s: [%s] %s (%.2f ms)",
                document.id,
                error_code,
                error_msg,
                duration_ms,
            )

            job.status = IngestionJobStatus.FAILED
            job.failed_at = datetime.now(UTC)
            job.error_code = error_code
            job.error_message = error_msg
            document.status = DocumentStatus.FAILED

            await session.commit()
            await session.refresh(job)
            await session.refresh(document)

            if isinstance(exc, IngestionException):
                raise exc
            raise IngestionException(
                message=f"Ingestion processing failed: {error_msg}",
                code=IngestionErrorCode.INTERNAL_ERROR,
            ) from exc

    @staticmethod
    async def get_job_by_id(
        session: AsyncSession,
        job_id: str,
        organization_id: str | None = None,
    ) -> IngestionJob:
        """Retrieve an IngestionJob by ID with optional tenant scoping."""
        stmt = select(IngestionJob).where(IngestionJob.id == job_id)
        if organization_id:
            stmt = stmt.where(IngestionJob.organization_id == organization_id)

        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundException(message="Ingestion job not found.")
        return job

    @staticmethod
    async def list_chunks(
        session: AsyncSession,
        document_id: str,
        organization_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DocumentChunk], int]:
        """List chunks belonging to a document with pagination."""
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.organization_id == organization_id,
        )
        count_stmt = select(func.count(DocumentChunk.id)).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.organization_id == organization_id,
        )

        total_res = await session.execute(count_stmt)
        total = total_res.scalar_one()

        stmt = stmt.order_by(DocumentChunk.chunk_index.asc()).limit(min(limit, 100)).offset(offset)
        items_res = await session.execute(stmt)
        items = list(items_res.scalars().all())

        return items, total
