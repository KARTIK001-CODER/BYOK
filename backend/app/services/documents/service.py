import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.embedding_job import EmbeddingJob, EmbeddingJobStatus
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.services.documents.storage import StorageService, get_storage_service
from app.services.documents.validation import (
    calculate_sha256,
    validate_upload_file,
)

logger = logging.getLogger("app.services.documents")


def sanitize_error_message(msg: str | None) -> str | None:
    """Sanitize error messages to prevent leakage of credentials or internal filesystem paths."""
    if not msg:
        return None
    # Strip database credentials / URIs
    msg = re.sub(r"://[^:]+:[^@]+@", "://***:***@", msg)
    # Strip local filesystem paths
    msg = re.sub(r"(?:[a-zA-Z]:[\\/]|/)[^\s:;,]+\.[a-zA-Z0-9]+", "[internal path]", msg)
    if len(msg) > 300:
        msg = msg[:297] + "..."
    return msg


class DocumentService:
    """Service managing document uploads, versions, metadata, and lifecycle."""

    @staticmethod
    def generate_storage_key(
        organization_id: str,
        kb_id: str,
        document_id: str,
        version_number: int,
        filename: str,
    ) -> str:
        """Generate deterministic, structured storage key."""
        return (
            f"org/{organization_id}/kb/{kb_id}/documents/{document_id}/v{version_number}/{filename}"
        )

    @staticmethod
    async def upload_document(
        session: AsyncSession,
        kb: KnowledgeBase,
        organization_id: str,
        user_id: str | None,
        original_filename: str,
        content: bytes,
        content_type: str | None = None,
        storage: StorageService | None = None,
    ) -> tuple[Document, DocumentVersion]:
        """
        Validate, store, and record a new document upload.
        """
        # Ensure tenant integrity
        if kb.organization_id != organization_id:
            raise ValidationException(
                message="Knowledge Base does not belong to the target organization."
            )

        storage_service = storage or get_storage_service()

        # 1. Validate File Format & Magic Bytes
        clean_filename, canonical_mime = validate_upload_file(
            filename=original_filename,
            content=content,
            content_type=content_type,
        )

        # 2. Cryptographic Checksum
        checksum = calculate_sha256(content)

        # 3. Duplicate Document Detection within Knowledge Base
        dup_stmt = select(Document).where(
            Document.knowledge_base_id == kb.id,
            Document.checksum == checksum,
            Document.deleted_at.is_(None),
        )
        dup_result = await session.execute(dup_stmt)
        existing_doc = dup_result.scalar_one_or_none()
        if existing_doc:
            raise ConflictException(
                message="Duplicate document detected in this knowledge base.",
                details={
                    "existing_document_id": existing_doc.id,
                    "existing_document_name": existing_doc.name,
                    "checksum": checksum,
                },
            )

        # 4. Generate Identifiers & Storage Key
        doc_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        storage_key = DocumentService.generate_storage_key(
            organization_id=organization_id,
            kb_id=kb.id,
            document_id=doc_id,
            version_number=1,
            filename=clean_filename,
        )

        # 5. Persist to Storage Abstraction
        uploaded_key = await storage_service.upload_file(
            storage_key=storage_key,
            content=content,
            content_type=canonical_mime,
        )

        # 6. Database Transaction
        try:
            doc = Document(
                id=doc_id,
                knowledge_base_id=kb.id,
                organization_id=organization_id,
                uploaded_by=user_id,
                name=clean_filename,
                original_filename=clean_filename,
                content_type=canonical_mime,
                file_size=len(content),
                storage_key=uploaded_key,
                checksum=checksum,
                status=DocumentStatus.UPLOADED,
                current_version=1,
            )
            doc_version = DocumentVersion(
                id=version_id,
                document_id=doc_id,
                version_number=1,
                storage_key=uploaded_key,
                checksum=checksum,
                file_size=len(content),
                content_type=canonical_mime,
                uploaded_by=user_id,
            )

            session.add(doc)
            session.add(doc_version)
            await session.commit()
            await session.refresh(doc)
            await session.refresh(doc_version)

            logger.info("Uploaded Document id=%s in KB id=%s", doc.id, kb.id)
            return doc, doc_version
        except Exception as exc:
            # Consistency cleanup on DB failure
            logger.error("DB commit failed for doc_id=%s. Cleaning up storage.", doc_id)
            await storage_service.delete_file(uploaded_key)
            raise exc

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        document_id: str,
        organization_id: str | None = None,
    ) -> Document:
        """Retrieve a document by ID with optional tenant check, aggregated chunk count, and latest error."""
        chunk_count_subq = (
            select(func.count(DocumentChunk.id))
            .where(DocumentChunk.document_id == Document.id)
            .correlate(Document)
            .scalar_subquery()
        )
        ingestion_err_subq = (
            select(IngestionJob.error_message)
            .where(
                IngestionJob.document_id == Document.id,
                IngestionJob.status == IngestionJobStatus.FAILED,
            )
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
            .correlate(Document)
            .scalar_subquery()
        )
        embedding_err_subq = (
            select(EmbeddingJob.error_message)
            .where(
                EmbeddingJob.document_id == Document.id,
                EmbeddingJob.status == EmbeddingJobStatus.FAILED,
            )
            .order_by(EmbeddingJob.created_at.desc())
            .limit(1)
            .correlate(Document)
            .scalar_subquery()
        )
        err_msg_col = func.coalesce(ingestion_err_subq, embedding_err_subq).label("error_message")

        stmt = (
            select(Document, chunk_count_subq.label("chunk_count"), err_msg_col)
            .where(Document.id == document_id)
        )
        if organization_id:
            stmt = stmt.where(Document.organization_id == organization_id)

        result = await session.execute(stmt)
        row = result.first()
        if row is None:
            raise NotFoundException(message="Document not found.")
        doc, count, err_msg = row
        if doc.deleted_at is not None:
            raise NotFoundException(message="Document not found.")
        doc.chunk_count = count or 0
        doc.error_message = sanitize_error_message(err_msg)
        return doc

    @staticmethod
    async def list_documents(
        session: AsyncSession,
        kb_id: str,
        organization_id: str,
        limit: int = 20,
        offset: int = 0,
        status: DocumentStatus | None = None,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> tuple[list[Document], int]:
        """List documents in a knowledge base with pagination, sorting, status filtering, chunk counts, and errors."""
        chunk_count_subq = (
            select(func.count(DocumentChunk.id))
            .where(DocumentChunk.document_id == Document.id)
            .correlate(Document)
            .scalar_subquery()
        )
        ingestion_err_subq = (
            select(IngestionJob.error_message)
            .where(
                IngestionJob.document_id == Document.id,
                IngestionJob.status == IngestionJobStatus.FAILED,
            )
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
            .correlate(Document)
            .scalar_subquery()
        )
        embedding_err_subq = (
            select(EmbeddingJob.error_message)
            .where(
                EmbeddingJob.document_id == Document.id,
                EmbeddingJob.status == EmbeddingJobStatus.FAILED,
            )
            .order_by(EmbeddingJob.created_at.desc())
            .limit(1)
            .correlate(Document)
            .scalar_subquery()
        )
        err_msg_col = func.coalesce(ingestion_err_subq, embedding_err_subq).label("error_message")

        stmt = select(Document, chunk_count_subq.label("chunk_count"), err_msg_col).where(
            Document.knowledge_base_id == kb_id,
            Document.organization_id == organization_id,
            Document.deleted_at.is_(None),
        )
        count_stmt = select(func.count(Document.id)).where(
            Document.knowledge_base_id == kb_id,
            Document.organization_id == organization_id,
            Document.deleted_at.is_(None),
        )

        if status:
            stmt = stmt.where(Document.status == status)
            count_stmt = count_stmt.where(Document.status == status)

        # Allowlist sort fields
        sort_field_map = {
            "created_at": Document.created_at,
            "updated_at": Document.updated_at,
            "name": Document.name,
            "file_size": Document.file_size,
        }
        sort_col = sort_field_map.get(sort_by, Document.created_at)
        if order.lower() == "asc":
            stmt = stmt.order_by(sort_col.asc())
        else:
            stmt = stmt.order_by(sort_col.desc())

        # Total count
        total_res = await session.execute(count_stmt)
        total = total_res.scalar_one()

        # Paginated results
        stmt = stmt.limit(min(limit, 100)).offset(offset)
        items_res = await session.execute(stmt)
        rows = items_res.all()
        items = []
        for doc, count, err_msg in rows:
            doc.chunk_count = count or 0
            doc.error_message = sanitize_error_message(err_msg)
            items.append(doc)

        return items, total

    @staticmethod
    async def update_document(
        session: AsyncSession,
        document: Document,
        name: str | None = None,
        status: DocumentStatus | None = None,
    ) -> Document:
        """Update document metadata or lifecycle status."""
        if name is not None:
            document.name = name
        if status is not None:
            document.status = status

        existing_count = getattr(document, "_chunk_count", 0)
        existing_err = getattr(document, "_error_message", None)
        await session.commit()
        await session.refresh(document)
        document.chunk_count = existing_count
        document.error_message = existing_err
        logger.info("Updated Document id=%s (status=%s)", document.id, document.status)
        return document

    @staticmethod
    async def archive_document(
        session: AsyncSession,
        document: Document,
    ) -> Document:
        """Set document status to ARCHIVED."""
        document.status = DocumentStatus.ARCHIVED
        await session.commit()
        await session.refresh(document)
        logger.info("Archived Document id=%s", document.id)
        return document

    @staticmethod
    async def delete_document(
        session: AsyncSession,
        document: Document,
        storage: StorageService | None = None,
    ) -> None:
        """Soft delete document metadata and mark deleted_at timestamp."""
        _ = storage
        document.deleted_at = datetime.now(UTC)
        await session.commit()
        logger.info("Soft-deleted Document id=%s", document.id)
