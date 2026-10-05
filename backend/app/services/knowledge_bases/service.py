import logging
import re

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.document import Document, DocumentStatus, EmbeddingStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_bases import KnowledgeBaseStatsResponse

logger = logging.getLogger("app.services.knowledge_bases")


def slugify(text: str) -> str:
    """Convert string to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "kb"


class KnowledgeBaseService:
    """Service handling Knowledge Base lifecycle and querying."""

    @staticmethod
    async def generate_unique_slug(
        session: AsyncSession,
        organization_id: str,
        name: str,
    ) -> str:
        """Generate a unique slug scoped within the organization."""
        base_slug = slugify(name)
        slug = base_slug
        counter = 1

        while True:
            stmt = select(KnowledgeBase.id).where(
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.slug == slug,
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none() is None:
                return slug
            counter += 1
            slug = f"{base_slug}-{counter}"

    @staticmethod
    async def create_knowledge_base(
        session: AsyncSession,
        organization_id: str,
        name: str,
        description: str | None = None,
        created_by: str | None = None,
    ) -> KnowledgeBase:
        """Create a new knowledge base for an organization."""
        slug = await KnowledgeBaseService.generate_unique_slug(
            session=session,
            organization_id=organization_id,
            name=name,
        )

        kb = KnowledgeBase(
            organization_id=organization_id,
            name=name,
            slug=slug,
            description=description,
            created_by=created_by,
            is_active=True,
        )
        session.add(kb)
        await session.commit()
        await session.refresh(kb)
        logger.info(
            "Created KnowledgeBase id=%s slug=%s for org_id=%s", kb.id, kb.slug, organization_id
        )
        return kb

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        kb_id: str,
        organization_id: str | None = None,
    ) -> KnowledgeBase:
        """Retrieve a KnowledgeBase by ID with optional tenant check."""
        stmt = select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        if organization_id:
            stmt = stmt.where(KnowledgeBase.organization_id == organization_id)

        result = await session.execute(stmt)
        kb = result.scalar_one_or_none()
        if kb is None:
            raise NotFoundException(message="Knowledge Base not found.")
        return kb

    @staticmethod
    async def list_knowledge_bases(
        session: AsyncSession,
        organization_ids: list[str],
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
    ) -> tuple[list[KnowledgeBase], int]:
        """List knowledge bases belonging to authorized organizations with pagination and search."""
        if not organization_ids:
            return [], 0

        # Base query
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.organization_id.in_(organization_ids),
            KnowledgeBase.is_active.is_(True),
        )
        count_stmt = select(func.count(KnowledgeBase.id)).where(
            KnowledgeBase.organization_id.in_(organization_ids),
            KnowledgeBase.is_active.is_(True),
        )

        if search and search.strip():
            search_pattern = f"%{search.strip()}%"
            stmt = stmt.where(KnowledgeBase.name.ilike(search_pattern))
            count_stmt = count_stmt.where(KnowledgeBase.name.ilike(search_pattern))

        # Count total
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        # Fetch page
        stmt = stmt.order_by(KnowledgeBase.created_at.desc()).limit(min(limit, 100)).offset(offset)
        items_result = await session.execute(stmt)
        items = list(items_result.scalars().all())

        return items, total

    @staticmethod
    async def update_knowledge_base(
        session: AsyncSession,
        kb: KnowledgeBase,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
    ) -> KnowledgeBase:
        """Update knowledge base details."""
        if name is not None and name != kb.name:
            kb.name = name
            kb.slug = await KnowledgeBaseService.generate_unique_slug(
                session, kb.organization_id, name
            )
        if description is not None:
            kb.description = description
        if is_active is not None:
            kb.is_active = is_active

        await session.commit()
        await session.refresh(kb)
        logger.info("Updated KnowledgeBase id=%s", kb.id)
        return kb

    @staticmethod
    async def delete_knowledge_base(
        session: AsyncSession,
        kb: KnowledgeBase,
    ) -> None:
        """Delete knowledge base and cascade to documents."""
        await session.delete(kb)
        await session.commit()
        logger.info("Deleted KnowledgeBase id=%s", kb.id)

    @staticmethod
    async def get_knowledge_base_stats(
        session: AsyncSession,
        kb_id: str,
        organization_id: str,
    ) -> KnowledgeBaseStatsResponse:
        """
        Aggregate document inventory and processing health metrics in a single SQL statement.
        Guarantees tenant scoping, excludes soft-deleted documents, and avoids N+1 queries.
        """
        chunk_subq = (
            select(func.coalesce(func.count(DocumentChunk.id), 0))
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(
                Document.knowledge_base_id == kb_id,
                Document.organization_id == organization_id,
                Document.deleted_at.is_(None),
                DocumentVersion.version_number == Document.current_version,
            )
            .scalar_subquery()
        )

        stmt = select(
            func.count(Document.id).label("total_documents"),
            chunk_subq.label("total_chunks"),
            func.coalesce(func.sum(Document.file_size), 0).label("total_file_size_bytes"),
            func.count(case((Document.status == DocumentStatus.READY, 1))).label("ready_documents"),
            func.count(
                case(
                    (
                        or_(
                            Document.status.in_(
                                [DocumentStatus.UPLOADING, DocumentStatus.PROCESSING]
                            ),
                            and_(
                                Document.status == DocumentStatus.READY,
                                Document.embedding_status.in_(
                                    [EmbeddingStatus.PROCESSING, EmbeddingStatus.PENDING]
                                ),
                            ),
                        ),
                        1,
                    )
                )
            ).label("processing_documents"),
            func.count(case((Document.status == DocumentStatus.FAILED, 1))).label(
                "failed_documents"
            ),
            func.count(
                case(
                    (
                        and_(
                            Document.status == DocumentStatus.READY,
                            or_(
                                Document.embedding_status.is_(None),
                                Document.embedding_status == EmbeddingStatus.PENDING,
                            ),
                        ),
                        1,
                    )
                )
            ).label("pending_embeddings"),
            func.count(case((Document.embedding_status == EmbeddingStatus.FAILED, 1))).label(
                "failed_embeddings"
            ),
        ).where(
            Document.knowledge_base_id == kb_id,
            Document.organization_id == organization_id,
            Document.deleted_at.is_(None),
        )

        res = await session.execute(stmt)
        row = res.one()

        return KnowledgeBaseStatsResponse(
            knowledge_base_id=kb_id,
            total_documents=row.total_documents or 0,
            total_chunks=row.total_chunks or 0,
            total_file_size_bytes=int(row.total_file_size_bytes or 0),
            ready_documents=row.ready_documents or 0,
            processing_documents=row.processing_documents or 0,
            failed_documents=row.failed_documents or 0,
            pending_embeddings=row.pending_embeddings or 0,
            failed_embeddings=row.failed_embeddings or 0,
        )
